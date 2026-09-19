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
GIT_ENV = {
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
}


def git(cwd: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *arguments],
        env={**os.environ, **GIT_ENV},
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    ).stdout


def release(
    cwd: Path, *arguments: str, git_available: bool = True
) -> subprocess.CompletedProcess[bytes]:
    path = os.environ["PATH"] if git_available else str(cwd / "no-programs")
    return subprocess.run(
        [sys.executable, "-I", "-m", "releasing", *arguments],
        cwd=cwd,
        env={**os.environ, **GIT_ENV, "PATH": path},
        capture_output=True,
        timeout=60,
        check=False,
    )


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    (tmp_path / "README.md").write_text("# Example\n", encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(CHANGELOG, encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "example"\nversion = "1.2.3"\n\n'
        '[tool.releasing]\nrepository = "foundata/example"\n',
        encoding="utf-8",
    )
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-q", "-m", "project: establish the example")
    return tmp_path


def test_version_check_prints_the_version_and_honours_tags(repository: Path) -> None:
    result = release(repository, "version", "check")
    assert (result.returncode, result.stdout, result.stderr) == (0, b"1.2.3\n", b"")
    git(repository, "tag", "-a", "v1.0.0", "-m", "version 1.0.0")
    result = release(repository, "version", "check", "--expect", "1.2.3")
    assert result.returncode == 1
    assert b"tag v1.2.3 does not point at the current revision" in result.stderr
    assert b"Traceback" not in result.stderr


def test_version_check_works_in_an_exported_tree_without_git(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Example\n", encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(CHANGELOG, encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "example"\nversion = "1.2.3"\n\n'
        '[tool.releasing]\nrepository = "foundata/example"\n',
        encoding="utf-8",
    )
    result = release(tmp_path, "version", "check", git_available=False)
    assert (result.returncode, result.stdout) == (0, b"1.2.3\n")


def test_version_bump_prints_diffs_and_refuses_dirty_sites(repository: Path) -> None:
    result = release(repository, "version", "bump", "1.3.0", "--no-lock")
    assert result.returncode == 0, result.stderr
    assert b'-version = "1.2.3"\n+version = "1.3.0"\n' in result.stdout
    assert git(repository, "status", "--porcelain").strip() == "M pyproject.toml"
    result = release(repository, "version", "bump", "1.4.0", "--no-lock")
    assert result.returncode == 1
    assert b"uncommitted changes in version files" in result.stderr
    result = release(repository, "version", "bump", "1.4.0", "--no-lock", "--force")
    assert result.returncode == 0, result.stderr
    # The changelog still names 1.2.3 as the latest release, so the check fails
    # until the changelog is released too.
    result = release(repository, "version", "check")
    assert result.returncode == 1
    assert b"latest released section must be [1.4.0]" in result.stderr
    assert release(repository, "changelog", "release", "1.4.0").returncode == 0
    assert release(repository, "version", "check").stdout == b"1.4.0\n"
