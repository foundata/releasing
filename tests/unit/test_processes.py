# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later

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
