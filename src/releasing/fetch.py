# SPDX-FileCopyrightText: foundata GmbH <https://foundata.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Read-only JSON over HTTPS: how this package asks a service a question.

A forge and a package index answer the few questions a release asks the same
way, and they answer them moments after the release changed the answer. What
makes such an answer trustworthy is one policy, not one per service: ask for a
revalidated document, wait a bounded time for it, and record the request in the
narration. Each caller keeps its own vocabulary for what a missing document
means, because to a forge it is "no release yet" and to an index it is "not
published".
"""

import json
import urllib.error
import urllib.request
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from releasing import reporting

TIMEOUT = 30.0
USER_AGENT = "foundata-releasing"
_HEADERS = {
    "Accept": "application/json",
    "User-Agent": USER_AGENT,
    # A release asks these questions moments after changing the answer, and an
    # anonymous request is served from a cache that may still hold the previous
    # one. Ask for a revalidated answer rather than a fast one.
    "Cache-Control": "no-cache",
}


class FetchError(RuntimeError):
    """The service could not be reached or answered unexpectedly."""


class NotFoundError(FetchError):
    """The service answered that there is no such document."""


class RateLimitError(FetchError):
    """The service refused the request because its allowance is used up.

    A forge meters anonymous requests per address, so an office that shares
    one connection runs out together. The answer is not wrong, only
    unavailable until ``reset``; the caller says how to ask differently.
    """

    def __init__(self, message: str, *, reset: datetime | None = None) -> None:
        """Record when the allowance returns, when the service said."""
        super().__init__(message)
        self.reset = reset


def get(
    url: str, *, headers: Mapping[str, str] | None = None, timeout: float = TIMEOUT
) -> Any:
    """GET one JSON document, narrating the request and what it answered.

    ``headers`` adds to the standard ones, for a credential a private
    repository needs. A 404 raises NotFoundError, which callers translate into
    their own answer; anything else that goes wrong raises FetchError.
    """
    request = urllib.request.Request(
        url, headers={**_HEADERS, **(headers or {})}, method="GET"
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            document = json.loads(response.read().decode("utf-8"))
            reporting.request("GET", url, response.status)
            return document
    except urllib.error.HTTPError as exc:
        # The error carries an open response body; release it either way.
        exc.close()
        reporting.request("GET", url, exc.code)
        if exc.code == 404:
            raise NotFoundError(f"{url}: HTTP 404 {exc.reason}") from exc
        if exc.code in (403, 429) and exc.headers.get("x-ratelimit-remaining") == "0":
            reset = _reset_time(exc.headers.get("x-ratelimit-reset"))
            until = f" until {reset:%H:%M}" if reset is not None else ""
            raise RateLimitError(
                f"{url}: HTTP {exc.code} {exc.reason}; the request allowance "
                f"is used up{until}",
                reset=reset,
            ) from exc
        raise FetchError(f"{url}: HTTP {exc.code} {exc.reason}") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        reporting.request("GET", url, "failed")
        raise FetchError(f"{url}: {exc}") from exc


def _reset_time(value: str | None) -> datetime | None:
    """The local time a Unix-timestamp header names, or None without one."""
    if value is None or not value.isdigit():
        return None
    return datetime.fromtimestamp(int(value)).astimezone()
