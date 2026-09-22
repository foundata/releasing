# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.support import captured

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


def test_status_reports_progress_and_exits_non_zero_until_complete(
    repository: Path,
) -> None:
    result = release(repository, "status", "1.0.0", "--offline")
    assert result.returncode == 1
    report = captured(result.stdout)
    assert "ok       changelog" in report
    assert "pending  tag            v1.0.0 does not exist locally" in report
    assert "unknown  index          not queried" in report
    assert b"incomplete" in result.stdout
    assert b"needs attention" not in result.stdout

    assert release(repository, "tag", "create", "1.0.0", "--offline").returncode == 0
    report = captured(release(repository, "status", "1.0.0", "--offline").stdout)
    assert "ok       tag " in report
    # Offline says "not queried" rather than "pending": the remote was never
    # asked, which is not the same as knowing the tag is absent there.
    assert "unknown  tag pushed     not queried" in report


def test_status_separates_a_broken_release_from_an_unfinished_one(
    repository: Path,
) -> None:
    git(repository, "tag", "v1.0.0")
    result = release(repository, "status", "1.0.0", "--offline")
    assert result.returncode == 1
    assert b"lightweight" in result.stdout
    assert b"needs attention, not continuation" in result.stdout


def test_status_compares_the_manifest_revision_with_the_tag(
    repository: Path, tmp_path: Path
) -> None:
    import json

    assert release(repository, "tag", "create", "1.0.0", "--offline").returncode == 0
    manifest = tmp_path / "artifacts.json"
    manifest.write_text(
        json.dumps(
            {
                "version": "1.0.0",
                "sourceRevision": "c" * 40,
                "artifacts": [{"filename": "example-1.0.0.tar.gz", "sha256": "b" * 64}],
            }
        ),
        encoding="utf-8",
    )
    result = release(
        repository, "status", "1.0.0", "--offline", "--manifest", str(manifest)
    )
    assert result.returncode == 1
    assert b"artifact revision" in result.stdout
    assert b"tag names" in result.stdout
    assert b"needs attention" in result.stdout
