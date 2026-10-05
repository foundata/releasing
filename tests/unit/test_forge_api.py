# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later
"""How a forge is asked: with a token, through its tool, or anonymously."""

import io
import json
import shutil
import subprocess
import urllib.error
import urllib.request
from email.message import Message
from typing import Any

import pytest
from typing_extensions import override

from releasing import forge_api, reporting
from releasing.forges import Forge

FORGE = Forge(
    "github",
    "foundata/example",
    "https://github.com",
    "https://raw.githubusercontent.com",
    "https://api.github.com",
    tool="gh",
    token_variables=("GH_TOKEN", "GITHUB_TOKEN"),
)
LATEST = "https://api.github.com/repos/foundata/example/releases/latest"


class Response(io.BytesIO):
    status = 200

    @override
    def __enter__(self) -> "Response":
        return self

    @override
    def __exit__(self, *_: object) -> None:
        self.close()


def https(
    monkeypatch: pytest.MonkeyPatch, payload: object, *, status: int | None = None
) -> list[Any]:
    """Serve one answer over HTTPS and record every request made."""
    seen: list[Any] = []

    def fake(request: Any, timeout: float = 0) -> Response:
        seen.append(request)
        if status is not None:
            headers = Message()
            if status in (403, 429):
                headers["x-ratelimit-remaining"] = "0"
                headers["x-ratelimit-reset"] = "1791171258"
            raise urllib.error.HTTPError(
                request.full_url, status, "reason", headers, io.BytesIO(b"{}")
            )
        return Response(json.dumps(payload).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    return seen


def tool(
    monkeypatch: pytest.MonkeyPatch,
    *,
    installed: bool = True,
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> list[list[str]]:
    """Install a fake gh and record every call."""
    calls: list[list[str]] = []
    monkeypatch.setattr(
        shutil,
        "which",
        lambda name: "/usr/bin/gh" if installed and name == "gh" else None,
    )

    def run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        env = kwargs.get("env")
        assert isinstance(env, dict) and env.get("GH_PROMPT_DISABLED") == "1"
        assert "token" not in " ".join(argv).lower()
        return subprocess.CompletedProcess(argv, returncode, stdout, stderr)

    monkeypatch.setattr(subprocess, "run", run)
    return calls


def narrated(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    lines: list[str] = []
    monkeypatch.setattr(
        reporting,
        "request",
        lambda method, url, status: lines.append(f"{method} {status}"),
    )
    return lines


def test_a_token_in_the_environment_is_used_before_anything_else(
    monkeypatch: pytest.MonkeyPatch, forge_tool: None
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "secret")
    calls = tool(monkeypatch, returncode=0, stdout='{"tag_name": "v9.9.9"}')
    seen = https(monkeypatch, {"tag_name": "v1.0.0"})

    assert forge_api.latest_release_tag(FORGE) == "v1.0.0"
    assert seen[0].get_header("Authorization") == "Bearer secret"
    assert calls == []


def test_gh_takes_precedence_over_github_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "actions")
    monkeypatch.setenv("GH_TOKEN", "mine")
    seen = https(monkeypatch, {"tag_name": "v1.0.0"})
    forge_api.latest_release_tag(FORGE)
    assert seen[0].get_header("Authorization") == "Bearer mine"


def test_a_logged_in_tool_answers_and_nothing_goes_anonymous(
    monkeypatch: pytest.MonkeyPatch, forge_tool: None
) -> None:
    calls = tool(monkeypatch, stdout='{"tag_name": "v1.0.0"}\n')
    seen = https(monkeypatch, None, status=500)
    lines = narrated(monkeypatch)

    assert forge_api.latest_release_tag(FORGE) == "v1.0.0"
    assert calls == [["/usr/bin/gh", "api", "repos/foundata/example/releases/latest"]]
    assert seen == []
    assert lines == ["GET via gh 200"]


def test_the_tool_reports_a_missing_release_as_no_release(
    monkeypatch: pytest.MonkeyPatch, forge_tool: None
) -> None:
    # gh prints the body to stdout and the status to stderr, and exits 1.
    tool(
        monkeypatch,
        returncode=1,
        stdout='{"message":"Not Found","status":"404"}',
        stderr="gh: Not Found (HTTP 404)\n",
    )
    seen = https(monkeypatch, {"tag_name": "v1.0.0"})
    lines = narrated(monkeypatch)

    assert forge_api.release_exists(FORGE, "v0.0.0") is False
    assert seen == []
    assert lines == ["GET via gh 404"]


@pytest.mark.parametrize("why", ["not installed", "not logged in"])
def test_without_a_usable_tool_the_question_goes_anonymous(
    monkeypatch: pytest.MonkeyPatch, forge_tool: None, why: str
) -> None:
    tool(
        monkeypatch,
        installed=why != "not installed",
        returncode=forge_api._NOT_LOGGED_IN,
        stderr="To get started with GitHub CLI, please run:  gh auth login\n",
    )
    seen = https(monkeypatch, {"tag_name": "v1.0.0"})

    assert forge_api.latest_release_tag(FORGE) == "v1.0.0"
    assert seen[0].get_header("Authorization") is None


def test_a_logged_in_tool_that_fails_is_the_forges_answer(
    monkeypatch: pytest.MonkeyPatch, forge_tool: None
) -> None:
    # Asking again anonymously would not change a forge-side failure, and it
    # would hide which way of asking failed.
    tool(monkeypatch, returncode=1, stderr="gh: Server Error (HTTP 502)\n")
    seen = https(monkeypatch, {"tag_name": "v1.0.0"})

    with pytest.raises(forge_api.ForgeError, match="HTTP 502"):
        forge_api.latest_release_tag(FORGE)
    assert seen == []


def test_the_tool_must_return_json(
    monkeypatch: pytest.MonkeyPatch, forge_tool: None
) -> None:
    tool(monkeypatch, stdout="not json")
    with pytest.raises(forge_api.ForgeError, match="returned no JSON"):
        forge_api.latest_release_tag(FORGE)


def test_an_anonymous_rate_limit_says_how_to_ask_as_a_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    https(monkeypatch, None, status=403)

    with pytest.raises(forge_api.ForgeError) as failure:
        forge_api.latest_release_tag(FORGE)
    message = str(failure.value)
    assert "allowance is used up until" in message
    assert "`gh auth login`" in message
    assert "GH_TOKEN" in message


def test_a_rate_limit_with_a_token_carries_no_anonymous_advice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GH_TOKEN", "secret")
    https(monkeypatch, None, status=429)

    with pytest.raises(forge_api.ForgeError) as failure:
        forge_api.latest_release_tag(FORGE)
    assert "allowance is used up" in str(failure.value)
    assert "auth login" not in str(failure.value)


def test_a_forge_without_a_tool_is_asked_anonymously(
    monkeypatch: pytest.MonkeyPatch, forge_tool: None
) -> None:
    bare = Forge("gitea", "foundata/example", "https://g", "https://r", "https://a")
    calls = tool(monkeypatch)
    seen = https(monkeypatch, {"tag_name": "v1.0.0"})

    assert forge_api.latest_release_tag(bare) == "v1.0.0"
    assert calls == []
    assert seen[0].full_url == "https://a/repos/foundata/example/releases/latest"
