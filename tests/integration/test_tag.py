# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration
GIT_ENV = {
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
    # Git transport stays on the local filesystem in these tests.
    "GIT_ALLOW_PROTOCOL": "file",
}
CHANGELOG = """# Changelog

## [Unreleased]

- Nothing worth mentioning right now.


## [1.0.0] - 2026-09-01

- All functionality.


[unreleased]: https://github.com/foundata/example/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/foundata/example/releases/tag/v1.0.0
"""


def git(cwd: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *arguments],
        env={**os.environ, **GIT_ENV},
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    ).stdout


def release(cwd: Path, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-I", "-m", "releasing", *arguments],
        cwd=cwd,
        env={**os.environ, **GIT_ENV},
        capture_output=True,
        timeout=120,
        check=False,
    )


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    remote = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "-q", "--bare", str(remote)],
        env={**os.environ, **GIT_ENV},
        check=True,
        timeout=60,
        capture_output=True,
    )
    root = tmp_path / "example"
    root.mkdir()
    (root / "README.md").write_text("# Example\n", encoding="utf-8")
    (root / "CHANGELOG.md").write_text(CHANGELOG, encoding="utf-8")
    (root / "pyproject.toml").write_text(
        '[project]\nname = "example"\nversion = "1.0.0"\n\n'
        '[tool.releasing]\nrepository = "foundata/example"\n',
        encoding="utf-8",
    )
    git(root.parent, "init", "-q", "-b", "main", str(root))
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "project: establish the example")
    git(root, "remote", "add", "origin", str(remote))
    git(root, "push", "-q", "-u", "origin", "main")
    return root


def test_create_check_and_delete_round_trip(repository: Path) -> None:
    result = release(repository, "tag", "create", "1.0.0", "--offline")
    assert (result.returncode, result.stdout) == (0, b"v1.0.0\n"), result.stderr
    assert git(repository, "cat-file", "-t", "v1.0.0").strip() == "tag"
    assert "version 1.0.0" in git(repository, "tag", "-n1", "v1.0.0")
    assert release(repository, "tag", "check", "1.0.0", "--offline").returncode == 0

    again = release(repository, "tag", "create", "1.0.0", "--offline")
    assert again.returncode == 1
    assert b"already exists locally" in again.stderr

    result = release(repository, "tag", "delete", "1.0.0", "--offline")
    assert result.returncode == 0, result.stderr
    assert git(repository, "tag", "--list") == ""


def test_create_refuses_a_dirty_tree_or_a_disagreeing_version(repository: Path) -> None:
    (repository / "untracked.txt").write_text("x\n", encoding="utf-8")
    result = release(repository, "tag", "create", "1.0.0", "--offline")
    assert result.returncode == 1
    assert b"working tree is not clean" in result.stderr
    (repository / "untracked.txt").unlink()

    result = release(repository, "tag", "create", "2.0.0", "--offline")
    assert result.returncode == 1
    assert b"expected 2.0.0, sites state 1.0.0" in result.stderr
    assert git(repository, "tag", "--list") == ""


def test_check_reports_a_lightweight_or_misplaced_tag(repository: Path) -> None:
    git(repository, "tag", "v1.0.0")
    result = release(repository, "tag", "check", "1.0.0", "--offline")
    assert result.returncode == 1
    assert b"lightweight" in result.stderr
    git(repository, "tag", "-d", "v1.0.0")

    git(repository, "commit", "-q", "--allow-empty", "-m", "repository: add a commit")
    git(repository, "tag", "-a", "v1.0.0", "HEAD~1", "-m", "version 1.0.0")
    result = release(repository, "tag", "check", "1.0.0", "--offline")
    assert result.returncode == 1
    assert b"points at" in result.stderr


def test_delete_refuses_while_the_remote_still_has_the_tag_pushed(
    repository: Path,
) -> None:
    assert release(repository, "tag", "create", "1.0.0", "--offline").returncode == 0
    git(repository, "push", "-q", "origin", "refs/tags/v1.0.0")
    result = release(repository, "tag", "delete", "1.0.0", "--offline")
    assert result.returncode == 0, result.stderr
    assert b"local, remote" in result.stdout
    assert git(repository, "ls-remote", "--tags", "origin") == ""
    missing = release(repository, "tag", "delete", "1.0.0", "--offline")
    assert missing.returncode == 1
    assert b"exists neither locally nor on the remote" in missing.stderr
