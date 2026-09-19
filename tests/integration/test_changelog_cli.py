# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration
CHANGELOG = """# Changelog

## [Unreleased]

- Something new.


## [1.2.3] - 2026-09-01

- Initial.


[unreleased]: https://github.com/foundata/example/compare/v1.2.3...HEAD
[1.2.3]: https://github.com/foundata/example/releases/tag/v1.2.3
"""


def release(cwd: Path, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-I", "-m", "releasing", "changelog", *arguments],
        cwd=cwd,
        env={**os.environ, "PATH": str(cwd / "no-programs")},
        capture_output=True,
        timeout=60,
        check=False,
    )


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "README.md").write_text("# Example\n", encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(CHANGELOG, encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "example"\nversion = "1.2.3"\n\n'
        '[tool.releasing]\nrepository = "foundata/example"\n',
        encoding="utf-8",
    )
    return tmp_path


def test_check_show_and_release_without_git_or_network(project: Path) -> None:
    assert release(project, "check").stdout == b"CHANGELOG.md: ok\n"
    assert release(project, "show", "1.2.3").stdout == b"- Initial.\n"
    result = release(project, "release", "1.3.0", "--date", "2026-09-20")
    assert (result.returncode, result.stdout) == (0, b"CHANGELOG.md: released 1.3.0\n")
    text = (project / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [1.3.0] - 2026-09-20\n\n- Something new.\n" in text
    assert (
        "[unreleased]: https://github.com/foundata/example/compare/v1.3.0...HEAD\n"
        in text
    )
    assert release(project, "check", "--version", "1.3.0").returncode == 0
    again = release(project, "release", "1.4.0")
    assert again.returncode == 1
    assert b"nothing to release" in again.stderr
    assert b"Traceback" not in again.stderr


def test_check_fails_on_a_broken_link(project: Path) -> None:
    path = project / "CHANGELOG.md"
    path.write_text(
        CHANGELOG.replace("compare/v1.2.3", "compare/v1.0.0"), encoding="utf-8"
    )
    result = release(project, "check")
    assert result.returncode == 1
    assert b"must compare v1.2.3...HEAD" in result.stderr
