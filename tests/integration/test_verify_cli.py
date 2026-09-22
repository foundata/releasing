# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later

from dataclasses import replace
from pathlib import Path

import pytest

from releasing import cli, verify
from releasing.artifacts import Manifest, ManifestEntry, dump_manifest
from releasing.forges import Forge

pytestmark = pytest.mark.integration
MANIFEST = Manifest(
    repository="foundata/example",
    version="1.0.0",
    source_revision="a" * 40,
    artifacts=(
        ManifestEntry("example-1.0.0.tar.gz", "1" * 64, 10),
        ManifestEntry("example-1.0.0-py3-none-any.whl", "2" * 64, 20),
        ManifestEntry("example-gui-1.0.0.tar.gz", "3" * 64, 30),
        ManifestEntry("example_gui-1.0.0-py3-none-any.whl", "4" * 64, 40),
    ),
    created="2026-09-20T10:00:00+00:00",
)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "README.md").write_text("# Example\n", encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "example"\nversion = "1.0.0"\n\n'
        '[tool.releasing]\nrepository = "foundata/example"\n',
        encoding="utf-8",
    )
    return tmp_path


def invoke(project: Path, manifest: Manifest, *arguments: str) -> int:
    path = project / "artifacts.json"
    path.write_text(dump_manifest(manifest), encoding="utf-8")
    return cli.main(["verify", str(path), "--project", str(project), *arguments])


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []

    def index_files(index: str, name: str, version: str) -> list[verify.IndexFile]:
        seen.append(f"index:{index}:{name}:{version}")
        entries = (
            MANIFEST.artifacts[:2] if name == "example" else MANIFEST.artifacts[2:]
        )
        return [verify.IndexFile(entry.filename, entry.sha256) for entry in entries]

    def installed_version(name: str, version: str, command: str | None = None) -> str:
        seen.append(f"install:{name}:{version}")
        return version

    def latest_tag(forge: Forge) -> str:
        seen.append(f"forge:{forge.repository}")
        return "v1.0.0"

    monkeypatch.setattr(verify, "index_files", index_files)
    monkeypatch.setattr(verify, "installed_version", installed_version)
    monkeypatch.setattr(verify, "latest_tag", latest_tag)
    return seen


@pytest.mark.parametrize("name", ["example", "example-gui", "Example.GUI"])
@pytest.mark.parametrize("no_install", [False, True])
def test_workspace_verifies_only_the_selected_distribution(
    project: Path,
    calls: list[str],
    capsys: pytest.CaptureFixture[str],
    name: str,
    no_install: bool,
) -> None:
    options = ["--distribution", name, *(["--no-install"] if no_install else [])]
    assert invoke(project, MANIFEST, *options) == 0
    name = name.lower().replace(".", "-")
    assert calls == [
        f"index:pypi:{name}:1.0.0",
        *([] if no_install else [f"install:{name}:1.0.0"]),
        "forge:foundata/example",
    ]
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == (
        "» Verified pypi serves the validated files for 1.0.0\n"
        + (
            ""
            if no_install
            else f"» Verified an isolated install reports {name} 1.0.0\n"
        )
        + "» Verified github reports v1.0.0 as the latest release\n"
    )


def test_single_hyphenated_distribution_is_inferred(
    project: Path, calls: list[str]
) -> None:
    manifest = replace(MANIFEST, artifacts=MANIFEST.artifacts[2:])
    assert invoke(project, manifest) == 0
    assert calls[0] == "index:pypi:example-gui:1.0.0"


@pytest.mark.parametrize("name", [None, "absent"])
def test_invalid_workspace_selection_stops_before_network_access(
    project: Path,
    calls: list[str],
    capsys: pytest.CaptureFixture[str],
    name: str | None,
) -> None:
    assert (
        invoke(project, MANIFEST, *([] if name is None else ["--distribution", name]))
        == 1
    )
    output = capsys.readouterr()
    assert output.out == ""
    assert (
        "pass --distribution" if name is None else "no artifacts for absent"
    ) in output.err
    assert calls == []


@pytest.mark.parametrize("problem", ["missing", "altered", "extra"])
def test_selected_distribution_still_requires_exact_published_files(
    project: Path,
    calls: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    problem: str,
) -> None:
    files = [
        verify.IndexFile(entry.filename, entry.sha256)
        for entry in MANIFEST.artifacts[:2]
    ]
    expected = ""
    if problem == "missing":
        files.pop()
        expected = "example-1.0.0-py3-none-any.whl: not published"
    elif problem == "altered":
        files[0] = replace(files[0], sha256="9" * 64)
        expected = "published digest differs"
    else:
        files.append(verify.IndexFile("example-1.0.0-1-py3-none-any.whl", "5" * 64))
        expected = "published but not in the manifest"

    def index_files(index: str, name: str, version: str) -> list[verify.IndexFile]:
        return files

    monkeypatch.setattr(verify, "index_files", index_files)
    assert invoke(project, MANIFEST, "--distribution", "example") == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert expected in output.err
    assert "example_gui" not in output.err
    assert calls == []


@pytest.mark.parametrize("stage", ["install", "forge"])
def test_verification_preserves_progress_before_a_later_failure(
    project: Path,
    calls: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    stage: str,
) -> None:
    def wrong_version(name: str, version: str, command: str | None = None) -> str:
        return "0.9.0"

    def wrong_tag(forge: Forge) -> str:
        return "v0.9.0"

    if stage == "install":
        monkeypatch.setattr(verify, "installed_version", wrong_version)
    else:
        monkeypatch.setattr(verify, "latest_tag", wrong_tag)
    assert invoke(project, MANIFEST, "--distribution", "example") == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err.startswith(
        "» Verified pypi serves the validated files for 1.0.0\n"
    )
    if stage == "forge":
        assert "» Verified an isolated install reports example 1.0.0" in output.err
    assert "0.9.0" in output.err
    assert "forge:foundata/example" not in calls
