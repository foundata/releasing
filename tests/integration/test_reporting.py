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

- Something new.


## [1.0.0] - 2026-09-01

- All functionality.


[unreleased]: https://github.com/foundata/example/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/foundata/example/releases/tag/v1.0.0
"""


def git(cwd: Path, *arguments: str, stdin: str | None = None) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *arguments],
        env={**os.environ, **GIT_ENV},
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
        input=stdin,
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
    assert "» Verified the working tree is clean" in story
    assert "» Exporting " in story
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


DRY_RUNS = [
    ("version bump", ("version", "bump", "1.1.0", "--no-lock")),
    ("changelog release", ("changelog", "release", "1.1.0")),
    ("tag create", ("tag", "create", "1.0.0", "--offline")),
    ("build", ("build", "--out", "dist", "--expect", "1.0.0")),
    ("artifacts manifest", None),
]


@pytest.mark.parametrize(
    "arguments",
    [case[1] for case in DRY_RUNS if case[1] is not None],
    ids=[case[0] for case in DRY_RUNS if case[1] is not None],
)
def test_a_dry_run_changes_nothing(
    repository: Path, arguments: tuple[str, ...]
) -> None:
    before = {
        path: path.read_bytes()
        for path in repository.iterdir()
        if path.is_file() and path.name != ".git"
    }

    result = release(repository, *arguments, "--dry-run")

    assert result.returncode == 0, result.stderr
    assert {path: path.read_bytes() for path in before} == before
    assert git(repository, "tag", "--list") == ""
    assert git(repository, "status", "--porcelain") == ""
    assert not (repository / "dist").exists()


def test_a_dry_run_reports_what_it_would_run(repository: Path) -> None:
    story = release(
        repository, "build", "--out", "dist", "--expect", "1.0.0", "--dry-run"
    ).stderr.decode()

    assert "» Would run: uv build --sdist" in story
    # A dry run may not invent what it cannot know.
    assert "recording their digests" in story
    assert "$ uv build" not in story


def test_a_dry_run_of_a_manifest_shows_it_instead_of_writing_it(
    repository: Path, tmp_path: Path
) -> None:
    artifact = tmp_path / "example-1.0.0.tar.gz"
    artifact.write_bytes(b"not a real distribution")
    target = tmp_path / "artifacts.json"

    result = release(
        repository,
        "artifacts",
        "manifest",
        str(artifact),
        "--out",
        str(target),
        "--version",
        "1.0.0",
        "--dry-run",
    )

    assert result.returncode == 1  # the file is not a distribution
    assert not target.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="no pty on Windows")
def test_a_terminal_gets_colour_and_a_pipe_does_not(repository: Path) -> None:
    # The decision is made against the real stream, so it is worth making once
    # against a real terminal rather than only against a stream double.
    import pty

    main, worker = pty.openpty()
    process = subprocess.Popen(
        [sys.executable, "-I", "-m", "releasing", "changelog", "check"],
        cwd=repository,
        stdout=subprocess.DEVNULL,
        stderr=worker,
        env={
            **os.environ,
            **GIT_ENV,
            "TERM": "xterm",
            "NO_COLOR": "",
            "FORCE_COLOR": "",
        },
    )
    os.close(worker)
    seen = bytearray()
    try:
        while chunk := os.read(main, 4096):
            seen += chunk
    except OSError:
        pass  # the terminal reports EIO once the child is gone
    finally:
        os.close(main)
    assert process.wait(timeout=60) == 0

    assert b"\x1b[32mChecked\x1b[0m" in seen, bytes(seen)
    assert (
        release(repository, "changelog", "check").stderr
        == b"\xc2\xbb Checked CHANGELOG.md\n"
    )


TOOL_TRAILER = (
    "release: prepare 1.1.0\n\n"
    "Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
)


def _credit_a_tool(root: Path) -> None:
    (root / "NOTES.md").write_text("# Notes\n", encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-q", "-F", "-", stdin=TOOL_TRAILER)


def test_tagging_refuses_a_commit_that_credits_a_tool(repository: Path) -> None:
    _credit_a_tool(repository)

    result = release(repository, "tag", "create", "1.0.0", "--offline")

    assert result.returncode == 1
    assert git(repository, "tag", "--list") == ""
    story = result.stderr.decode()
    assert "would publish a tool attribution" in story
    assert "co-authored-by: Claude Opus 5 (1M context)" in story
    assert "--allow-tool-attribution" in story


def test_the_flag_publishes_it_anyway_and_says_so(repository: Path) -> None:
    _credit_a_tool(repository)

    result = release(
        repository, "tag", "create", "1.0.0", "--offline", "--allow-tool-attribution"
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == b"v1.0.0\n"
    assert b"WARNING: publishing 1 tool attribution(s)" in result.stderr
    # The refusal that would have named it never appeared, so the bypass has to.
    assert b"co-authored-by: Claude Opus 5 (1M context)" in result.stderr


def test_pushing_checks_every_commit_it_would_send(repository: Path) -> None:
    # The tagged commit is clean; the one behind it is not, and the push would
    # publish both.
    release(repository, "tag", "create", "1.0.0", "--offline")
    _credit_a_tool(repository)
    git(repository, "commit", "-q", "--allow-empty", "-m", "chore: after")

    result = release(repository, "push", "1.0.0")

    assert result.returncode == 1
    assert "would publish a tool attribution" in result.stderr.decode()
    assert git(repository, "log", "--oneline", "origin/main..main").count("\n") == 2


def test_a_declaration_may_allow_one_rule(repository: Path) -> None:
    text = (repository / "pyproject.toml").read_text(encoding="utf-8")
    (repository / "pyproject.toml").write_text(
        text + 'allowed-attribution = ["assisted-by"]\n', encoding="utf-8"
    )
    (repository / "NOTES.md").write_text("# Notes\n", encoding="utf-8")
    git(repository, "add", ".")
    git(repository, "commit", "-q", "-F", "-", stdin="feat: x\n\nAssisted-by: a tool")

    result = release(repository, "tag", "create", "1.0.0", "--offline")

    assert result.returncode == 0, result.stderr
    assert b"Checked 1 commit(s) for attribution" in result.stderr
