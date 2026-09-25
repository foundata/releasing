# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.support import captured

pytestmark = pytest.mark.integration


def invoke(cwd: Path, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-I", "-m", "releasing", "config", "check", *arguments],
        cwd=cwd,
        env={**os.environ, "PATH": str(cwd / "no-programs")},
        capture_output=True,
        timeout=15,
        check=False,
    )


def test_config_check_reports_the_effective_declaration(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# x\n", encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "example"\n\n[tool.releasing]\n'
        'repository = "foundata/example"\n',
        encoding="utf-8",
    )
    result = invoke(tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stderr == b""
    assert captured(result.stdout) == (
        "pyproject.toml: valid release declaration\n"
        "repository: foundata/example (github)\n"
        "ecosystem: python, index: pypi\n"
        "version files: pyproject.toml\n"
        "changelog: CHANGELOG.md\n"
        "tag: vX.Y.Z\n"
        "dependency pins: none\n"
        "allowed attribution: none\n"
        "readme: README.md -> refs/tags/{tag}\n"
    )


def test_config_check_reports_the_keys_a_project_declares(tmp_path: Path) -> None:
    # Every declared value is printed, so the effective declaration can be
    # read off one report instead of the file plus the defaults.
    (tmp_path / "README.md").write_text("# x\n", encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "example"\n\n[tool.releasing]\n'
        'repository = "foundata/example"\n'
        'allowed-attribution = ["assisted-by: ^[^<]*$"]\n'
        'dependency-pins = [{ file = "pyproject.toml", name = "example" }]\n',
        encoding="utf-8",
    )

    result = invoke(tmp_path)

    assert result.returncode == 0, result.stderr
    assert "dependency pins: example in pyproject.toml\n" in captured(result.stdout)
    assert "allowed attribution: assisted-by: ^[^<]*$\n" in captured(result.stdout)


def test_config_check_names_a_hidden_standalone_declaration(tmp_path: Path) -> None:
    # The report names the file it read, and the command finds the dotted name
    # in the working directory the same way.
    (tmp_path / "README.md").write_text("# x\n", encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")
    (tmp_path / "VERSION").write_text("1.0.0\n", encoding="utf-8")
    (tmp_path / ".releasing.toml").write_text(
        'repository = "foundata/example"\nversion-files = ["VERSION"]\n',
        encoding="utf-8",
    )

    result = invoke(tmp_path)

    assert result.returncode == 0, result.stderr
    assert ".releasing.toml: valid release declaration\n" in captured(result.stdout)


def test_config_check_fails_with_a_reason_and_no_traceback(tmp_path: Path) -> None:
    (tmp_path / "releasing.toml").write_text(
        'repository = "foundata/example"\nversion-files = ["absent.py"]\n',
        encoding="utf-8",
    )
    result = invoke(tmp_path, "--project", str(tmp_path))
    assert result.returncode == 1
    assert result.stdout == b""
    assert b"absent.py" in result.stderr
    assert b"Traceback" not in result.stderr
