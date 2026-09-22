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


def test_the_story_goes_to_stderr_and_the_product_to_stdout(repository: Path) -> None:
    result = release(repository, "tag", "create", "1.0.0", "--offline")

    assert result.returncode == 0, result.stderr
    # The product: exactly what the command made, nothing else.
    assert result.stdout == b"v1.0.0\n"
    story = result.stderr.decode()
    assert "» the working tree is clean" in story
    assert "» exporting " in story
    assert "$ git -C " in story
    assert "tag -a v1.0.0" in story


def test_an_echoed_command_names_the_program_not_its_path(repository: Path) -> None:
    # The line is for a reader and stays runnable: the program was found in
    # PATH, so its plain name is what belongs on screen.
    story = release(repository, "tag", "create", "1.0.0", "--offline").stderr.decode()

    echoed = [line for line in story.splitlines() if line.startswith("$ ")]
    assert echoed, story
    assert all(line.startswith("$ git ") for line in echoed), echoed


@pytest.mark.parametrize("placement", ["before", "after"])
def test_quiet_keeps_the_product_and_drops_the_story(
    repository: Path, placement: str
) -> None:
    arguments = (
        ("--quiet", "tag", "create", "1.0.0", "--offline")
        if placement == "before"
        else ("tag", "create", "1.0.0", "--offline", "--quiet")
    )

    result = release(repository, *arguments)

    assert result.returncode == 0, result.stderr
    assert result.stdout == b"v1.0.0\n"
    assert result.stderr == b""


def test_quiet_never_suppresses_an_error(repository: Path) -> None:
    result = release(repository, "tag", "create", "2.0.0", "--offline", "--quiet")

    assert result.returncode == 1
    assert result.stdout == b""
    assert b"expected 2.0.0, sites state 1.0.0" in result.stderr


def test_a_library_caller_narrates_nothing(repository: Path, tmp_path: Path) -> None:
    # conclear drives this package inside its own release gate; stray output
    # would land in that gate's evidence.
    script = (
        "from pathlib import Path\n"
        "from releasing import _source_export\n"
        f"_source_export.export(Path({str(repository)!r}), 'HEAD',"
        f" Path({str(tmp_path / 'exported')!r}))\n"
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        timeout=120,
        check=True,
        env={**os.environ, **GIT_ENV},
    )

    assert result.stdout == b""
    assert result.stderr == b""
    assert (tmp_path / "exported" / "pyproject.toml").is_file()
