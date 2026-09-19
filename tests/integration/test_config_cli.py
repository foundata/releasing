# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import subprocess
import sys
from pathlib import Path

import pytest

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
    assert result.stdout.decode() == (
        "pyproject.toml: valid release declaration\n"
        "repository: foundata/example (github)\n"
        "ecosystem: python, index: pypi\n"
        "version files: pyproject.toml\n"
        "changelog: CHANGELOG.md\n"
        "tag: vX.Y.Z\n"
        "readme: README.md -> refs/tags/{tag}\n"
    )


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
