# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later

import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import cast

import pytest
from packaging.specifiers import SpecifierSet

from tests import check_dependency_floors, check_windows
from tests.support import write_lf


def test_dependency_floors_follow_the_declared_requirements() -> None:
    assert check_dependency_floors.dependency_floors(
        [
            "markdown-it-py>=3.0,<5",
            "packaging>=23.2",
            "typing-extensions>=4.4",
            "pyyaml>=6",
        ]
    ) == (
        "markdown-it-py==3.0",
        "packaging==23.2",
        "typing-extensions==4.4",
        "pyyaml==6",
    )
    assert str(check_dependency_floors.minimum(SpecifierSet(">=3.11"))) == "3.11"


@pytest.mark.parametrize("requirement", ["example<5", "example>3", "example>=3,!=3"])
def test_unusable_dependency_floors_are_not_silently_skipped(requirement: str) -> None:
    with pytest.raises(ValueError, match="inclusive minimum"):
        check_dependency_floors.dependency_floors([requirement])


@pytest.mark.parametrize(
    "requirement", ["example[extra]>=3", 'example>=3; sys_platform == "win32"']
)
def test_conditional_dependencies_require_an_explicit_floor_case(
    requirement: str,
) -> None:
    with pytest.raises(ValueError, match="dedicated floor case"):
        check_dependency_floors.dependency_floors([requirement])


def test_floor_verification_refuses_a_newer_installed_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(check_dependency_floors, "version", lambda name: "4.15.0")
    with pytest.raises(ValueError, match=r"expected typing-extensions==4\.4"):
        check_dependency_floors.verify_installed(["typing-extensions==4.4"])


@pytest.mark.parametrize("exit_code", [0, 7])
def test_the_floor_runner_pins_runtime_dependencies_and_propagates_test_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exit_code: int
) -> None:
    write_lf(
        tmp_path / "pyproject.toml",
        '[project]\nrequires-python = ">=3.11"\ndependencies = ["packaging>=23.2"]\n',
    )
    monkeypatch.setattr(check_dependency_floors, "ROOT", tmp_path)
    seen: list[list[str]] = []

    def run(
        command: Sequence[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        seen.append(list(command))
        assert kwargs["cwd"] == tmp_path
        return subprocess.CompletedProcess(command, exit_code)

    monkeypatch.setattr(subprocess, "run", run)
    assert check_dependency_floors.main([]) == exit_code
    assert seen == [
        [
            "uv",
            "run",
            "--locked",
            "--isolated",
            "--python",
            "3.11",
            "--with",
            "packaging==23.2",
            "python",
            str(Path(check_dependency_floors.__file__).resolve()),
            "--verify-and-test",
        ]
    ]


def test_the_windows_entry_point_refuses_a_non_native_host() -> None:
    assert check_windows.main([], platform="linux") == 2


@pytest.fixture
def windows_project(tmp_path: Path) -> Path:
    root = tmp_path / "checkout"
    root.mkdir()
    write_lf(root / "pyproject.toml", '[project]\nversion = "5.0.0"\n')
    return root


@pytest.fixture
def windows_commands(monkeypatch: pytest.MonkeyPatch) -> list[tuple[list[str], Path]]:
    calls: list[tuple[list[str], Path]] = []

    def run(
        command: Sequence[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        cwd = kwargs["cwd"]
        assert isinstance(cwd, Path)
        calls.append((list(command), cwd))
        if "--out" in command:
            dist = Path(command[command.index("--out") + 1])
            dist.mkdir()
            (dist / "releasing-5.0.0-py3-none-any.whl").write_bytes(b"wheel")
            (dist / "releasing-5.0.0.tar.gz").write_bytes(b"sdist")
        return subprocess.CompletedProcess(command, 0, stdout="")

    monkeypatch.setattr(subprocess, "run", run)
    return calls


def test_windows_gate_checks_and_smokes_the_installed_wheel_outside_the_checkout(
    windows_project: Path, windows_commands: list[tuple[list[str], Path]]
) -> None:
    check_windows.check(windows_project, "3.14")
    commands = [command for command, _ in windows_commands]
    uv = ["uv", "run", "--locked", "--isolated", "--python", "3.14"]
    assert [*uv, "pytest", "-q"] in commands
    assert [*uv, "mypy"] in commands
    assert [*uv, "python", "tests/check_markdown.py"] in commands
    smoke, cwd = windows_commands[-1]
    assert Path(smoke[0]).parts[-2:] == ("Scripts", "python.exe")
    assert smoke[1:3] == ["-I", str(windows_project / "tests" / "smoke_installed.py")]
    assert Path(smoke[3]).parts[-2:] == ("Scripts", "release.exe")
    assert smoke[4] == "5.0.0"
    assert cwd != windows_project
    assert not cwd.exists()
    assert any(command[:3] == ["uv", "pip", "install"] for command in commands)


def test_windows_gate_stops_before_checks_when_tracked_files_are_dirty(
    windows_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def run(
        command: Sequence[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        calls.append(list(command))
        return subprocess.CompletedProcess(command, 0, stdout=" M changed.py\n")

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(ValueError, match="tracked files differ"):
        check_windows.check(windows_project, "3.14")
    assert len(calls) == 1


def test_windows_gate_stops_and_cleans_up_after_an_install_failure(
    windows_project: Path,
    windows_commands: list[tuple[list[str], Path]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    previous = cast(Callable[..., subprocess.CompletedProcess[str]], subprocess.run)

    def run(
        command: Sequence[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        result = previous(command, **kwargs)
        if list(command[:3]) == ["uv", "pip", "install"]:
            raise subprocess.CalledProcessError(7, command)
        return result

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(subprocess.CalledProcessError) as failed:
        check_windows.check(windows_project, "3.14")
    assert failed.value.returncode == 7
    command, cwd = windows_commands[-1]
    assert command[:3] == ["uv", "pip", "install"]
    assert not cwd.exists()
