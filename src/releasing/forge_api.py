# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later
"""The small read-only part of a forge API the release steps need.

Two questions only: does a release exist for this tag, and which tag does the
forge report as the latest release. Anything that creates a release stays with
the forge's own command-line tool.

A forge meters anonymous requests per address, and an office shares one, so a
release should not have to ask anonymously when the person running it is
logged in. Each question is asked in one of three ways, the first that can
answer: with a token the environment provides, through the forge's own tool
and the login it holds, or anonymously. The token never leaves the process it
arrived in, and the tool's credential never enters this one.
"""

import json
import os
import re
import shutil
import subprocess
from typing import Any

from releasing import fetch, reporting
from releasing.forges import Forge

# gh exits with this status when no account is logged in; the tool is then
# installed but cannot answer, which is different from a failed request.
_NOT_LOGGED_IN = 4
_TOOL_STATUS = re.compile(r"\(HTTP (\d{3})\)")


class ForgeError(RuntimeError):
    """The forge could not be reached or answered unexpectedly."""


def release_exists(forge: Forge, tag: str) -> bool:
    """Whether the forge has a release for ``tag``."""
    return _request(forge, forge.release_by_tag_path(tag)) is not None


def latest_release_tag(forge: Forge) -> str | None:
    """The tag the forge reports as its latest release, or None when there is none."""
    document = _request(forge, forge.latest_release_path())
    if document is None:
        return None
    tag = document.get("tag_name") if isinstance(document, dict) else None
    if not isinstance(tag, str) or not tag:
        raise ForgeError(f"{forge.name}: latest release has no tag name")
    return tag


def _request(forge: Forge, path: str) -> Any | None:
    """GET one document of the forge's API, or None when it has no such document."""
    url = f"{forge.api}/{path}"
    token = _token(forge)
    if token is not None:
        try:
            return _over_https(url, {"Authorization": f"Bearer {token}"})
        except fetch.RateLimitError as exc:
            raise ForgeError(str(exc)) from exc
    answered, document = _through_tool(forge, path, url)
    if answered:
        return document
    try:
        return _over_https(url, {})
    except fetch.RateLimitError as exc:
        raise ForgeError(f"{exc}; {_hint(forge)}") from exc


def _token(forge: Forge) -> str | None:
    for name in forge.token_variables:
        value = os.environ.get(name)
        if value:
            return value
    return None


def _over_https(url: str, headers: dict[str, str]) -> Any | None:
    """GET over HTTPS; a rate limit is left to the caller, who knows how it asked."""
    try:
        return fetch.get(url, headers=headers)
    except fetch.NotFoundError:
        return None
    except fetch.RateLimitError:
        raise
    except fetch.FetchError as exc:
        raise ForgeError(str(exc)) from exc


def _through_tool(forge: Forge, path: str, url: str) -> tuple[bool, Any | None]:
    """Ask through the forge's own tool: (answered, document).

    Not answered means the tool is absent or holds no login, and the question
    goes on to the next way of asking. A tool that is logged in and fails has
    answered: its failure is the forge's, and asking again anonymously would
    not change it.
    """
    if forge.tool is None:
        return False, None
    program = shutil.which(forge.tool)
    if program is None:
        return False, None
    try:
        result = subprocess.run(
            [program, "api", path],
            capture_output=True,
            text=True,
            timeout=fetch.TIMEOUT,
            check=False,
            # The tool must answer or fail on its own; it may not ask anything
            # back, and its own notices would be mistaken for the answer.
            env={**os.environ, "GH_PROMPT_DISABLED": "1", "GH_NO_UPDATE_NOTIFIER": "1"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ForgeError(f"{forge.tool} api {path}: {exc}") from exc
    if result.returncode == _NOT_LOGGED_IN:
        return False, None
    method = f"GET via {forge.tool}"
    if result.returncode == 0:
        reporting.request(method, url, 200)
        try:
            return True, json.loads(result.stdout)
        except ValueError as exc:
            raise ForgeError(f"{forge.tool} returned no JSON for {url}: {exc}") from exc
    found = _TOOL_STATUS.search(result.stderr)
    status = int(found.group(1)) if found else None
    reporting.request(method, url, status if status is not None else "failed")
    if status == 404:
        return True, None
    detail = (
        result.stderr.strip() or f"{forge.tool} exited with status {result.returncode}"
    )
    raise ForgeError(f"{url}: {detail}")


def _hint(forge: Forge) -> str:
    ways = []
    if forge.tool is not None:
        ways.append(f"log in with `{forge.tool} auth login`")
    if forge.token_variables:
        ways.append(f"set {forge.token_variables[0]}")
    if not ways:
        return "wait until the allowance resets"
    return (
        " or ".join(ways) + " so requests are made as a user, whose allowance is larger"
    )
