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
        timeout=180,
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


def remote_refs(repository: Path) -> str:
    return git(repository, "ls-remote", "origin")


def test_push_sends_the_branch_before_the_tag(repository: Path) -> None:
    git(repository, "commit", "-q", "--allow-empty", "-m", "release: prepare 1.0.0")
    assert release(repository, "tag", "create", "1.0.0", "--offline").returncode == 0

    result = release(repository, "push", "1.0.0")
    assert result.returncode == 0, result.stderr
    assert result.stdout == b""
    assert b"Pushed main to origin" in result.stderr
    assert b"Pushed v1.0.0 to origin" in result.stderr
    refs = remote_refs(repository)
    assert "refs/tags/v1.0.0" in refs
    assert git(repository, "rev-parse", "HEAD").strip() in refs


def test_dry_run_sends_nothing(repository: Path) -> None:
    assert release(repository, "tag", "create", "1.0.0", "--offline").returncode == 0
    result = release(repository, "push", "1.0.0", "--dry-run")
    assert result.returncode == 0, result.stderr
    assert result.stdout == b""
    assert b"Would push main" in result.stderr
    assert "refs/tags/v1.0.0" not in remote_refs(repository)


def test_push_refuses_a_tag_the_branch_does_not_contain(repository: Path) -> None:
    # Tag one commit, then reset the branch back past it: pushing the tag would
    # publish a commit that is on no branch.
    git(repository, "commit", "-q", "--allow-empty", "-m", "release: prepare 1.0.0")
    assert release(repository, "tag", "create", "1.0.0", "--offline").returncode == 0
    git(repository, "reset", "-q", "--hard", "HEAD~1")

    result = release(repository, "push", "1.0.0")
    assert result.returncode == 1
    assert b"does not contain v1.0.0" in result.stderr
    assert "refs/tags/v1.0.0" not in remote_refs(repository)


def test_push_refuses_a_missing_or_lightweight_tag(repository: Path) -> None:
    result = release(repository, "push", "1.0.0")
    assert result.returncode == 1
    assert b"does not exist" in result.stderr

    git(repository, "tag", "v1.0.0")
    result = release(repository, "push", "1.0.0")
    assert result.returncode == 1
    assert b"lightweight" in result.stderr
    assert "refs/tags/v1.0.0" not in remote_refs(repository)


def test_push_refuses_a_detached_head(repository: Path) -> None:
    assert release(repository, "tag", "create", "1.0.0", "--offline").returncode == 0
    git(repository, "checkout", "-q", "--detach", "HEAD")
    result = release(repository, "push", "1.0.0")
    assert result.returncode == 1
    assert b"detached" in result.stderr


def test_push_refuses_when_the_revision_disagrees_with_the_version(
    repository: Path,
) -> None:
    assert release(repository, "tag", "create", "1.0.0", "--offline").returncode == 0
    # Move the sources on, then tag a later commit as the same version.
    (repository / "pyproject.toml").write_text(
        '[project]\nname = "example"\nversion = "2.0.0"\n\n'
        '[tool.releasing]\nrepository = "foundata/example"\n',
        encoding="utf-8",
    )
    git(repository, "commit", "-qam", "release: prepare 2.0.0")
    git(repository, "tag", "-d", "v1.0.0")
    git(repository, "tag", "-a", "v1.0.0", "-m", "version 1.0.0")

    result = release(repository, "push", "1.0.0")
    assert result.returncode == 1
    assert b"expected 1.0.0, sites state 2.0.0" in result.stderr
    assert "refs/tags/v1.0.0" not in remote_refs(repository)


def fork(repository: Path, name: str) -> Path:
    """Add a second remote and make the branch track it, as a fork does."""
    other = repository.parent / f"{name}.git"
    subprocess.run(
        ["git", "init", "-q", "--bare", str(other)],
        env={**os.environ, **GIT_ENV},
        check=True,
        timeout=60,
        capture_output=True,
    )
    git(repository, "remote", "add", name, str(other))
    git(repository, "push", "-q", "-u", name, "main")
    return other


def test_the_remote_is_the_one_the_branch_tracks(repository: Path) -> None:
    # A fork releases to a remote that is not called origin, and pushing to
    # origin would publish the release somewhere nobody is watching.
    fork(repository, "upstream")
    assert release(repository, "tag", "create", "1.0.0", "--offline").returncode == 0

    result = release(repository, "push", "1.0.0")

    assert result.returncode == 0, result.stderr
    assert b"to upstream" in result.stderr
    assert "refs/tags/v1.0.0" in git(repository, "ls-remote", "upstream")
    assert git(repository, "ls-remote", "--tags", "origin") == ""


def test_a_named_remote_wins_over_the_tracked_one(repository: Path) -> None:
    fork(repository, "upstream")
    assert release(repository, "tag", "create", "1.0.0", "--offline").returncode == 0

    result = release(repository, "push", "1.0.0", "--remote", "origin")

    assert result.returncode == 0, result.stderr
    assert "refs/tags/v1.0.0" in git(repository, "ls-remote", "origin")
    assert git(repository, "ls-remote", "--tags", "upstream") == ""


def test_a_branch_that_tracks_nothing_falls_back_to_origin(repository: Path) -> None:
    git(repository, "branch", "--unset-upstream")
    assert release(repository, "tag", "create", "1.0.0", "--offline").returncode == 0

    result = release(repository, "push", "1.0.0")

    assert result.returncode == 0, result.stderr
    assert "refs/tags/v1.0.0" in remote_refs(repository)
