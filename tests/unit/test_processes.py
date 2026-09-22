# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later

import subprocess
import sys
from pathlib import Path

import pytest

from releasing import processes


def test_remote_git_calls_are_bounded_and_do_not_prompt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # An unreachable remote must fail rather than wait for the local timeout
    # or for credentials nobody is there to supply.
    seen: dict[str, object] = {}

    def fake(argv: list[str], **kwargs: object) -> str:
        seen.update(kwargs)
        seen["argv"] = argv
        return ""

    monkeypatch.setattr(processes, "executable", lambda name: Path("/usr/bin") / name)
    monkeypatch.setattr(processes, "run", fake)
    monkeypatch.delenv("GIT_SSH_COMMAND", raising=False)

    processes.git(tmp_path, "ls-remote", "origin", remote=True)
    assert seen["timeout"] == processes.REMOTE_TIMEOUT
    environment = seen["environment"]
    assert isinstance(environment, dict)
    assert environment["GIT_TERMINAL_PROMPT"] == "0"
    assert "BatchMode=yes" in environment["GIT_SSH_COMMAND"]

    seen.clear()
    processes.git(tmp_path, "status", "--porcelain")
    assert seen["timeout"] == processes.TIMEOUT
    assert seen["environment"] is None


def test_a_configured_ssh_command_is_left_alone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: dict[str, object] = {}
    monkeypatch.setattr(processes, "executable", lambda name: Path("/usr/bin") / name)
    monkeypatch.setattr(
        processes, "run", lambda argv, **kwargs: seen.update(kwargs) or ""
    )
    monkeypatch.setenv("GIT_SSH_COMMAND", "ssh -i /keys/id")
    processes.git(tmp_path, "ls-remote", "origin", remote=True)
    environment = seen["environment"]
    assert isinstance(environment, dict)
    assert "GIT_SSH_COMMAND" not in environment


def test_a_streamed_child_reports_to_our_standard_error(
    capfd: pytest.CaptureFixture[str],
) -> None:
    # A child's own output is part of the story. Our standard output carries
    # the product, such as a changelog section piped into a forge tool, so
    # nothing a child prints may land there.
    script = "import sys; print('to stdout'); print('to stderr', file=sys.stderr)"
    returned = processes.run([sys.executable, "-c", script], stream=True)

    captured = capfd.readouterr()
    assert returned == ""
    assert captured.out == ""
    assert "to stdout" in captured.err
    assert "to stderr" in captured.err


def test_a_streamed_child_that_fails_is_reported_like_any_other() -> None:
    with pytest.raises(processes.ProcessError, match="failed with status 3"):
        processes.run([sys.executable, "-c", "raise SystemExit(3)"], stream=True)


def test_the_story_stream_falls_back_when_stderr_has_no_descriptor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Detached:
        def fileno(self) -> int:
            raise OSError("no descriptor here")

    monkeypatch.setattr(sys, "stderr", Detached())
    assert processes._story_stream() == subprocess.DEVNULL


@pytest.mark.parametrize(
    "argv, expected",
    [
        (
            ["/usr/bin/git", "-C", "/repo", "archive", "--format=tar", "HEAD"],
            "git archive",
        ),
        (["/usr/bin/uv", "build", "--sdist", "--out-dir", "/tmp/x"], "uv build"),
        (["/usr/bin/gh", "release", "create", "v2.2.0"], "gh release"),
        (["/usr/bin/python3", "-c", "import sys; print('x')"], "python3"),
        (["/usr/bin/somebinary"], "somebinary"),
    ],
)
def test_a_failure_names_the_program_and_its_subcommand(
    argv: list[str], expected: str
) -> None:
    # The resolved executable is an absolute path, so "git failed" would say
    # less than "git archive failed" when a release stops.
    assert processes.describe(argv) == expected


def test_a_failing_command_reports_the_described_name(tmp_path: Path) -> None:
    with pytest.raises(processes.ProcessError, match=r"^git status failed with status"):
        processes.git(tmp_path, "status")
