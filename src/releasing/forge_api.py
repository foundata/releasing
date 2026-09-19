# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later
"""The small read-only part of a forge API the release steps need.

Two questions only: does a release exist for this tag, and which tag does the
forge report as the latest release. Requests are anonymous and read-only; a
token is used only when the environment provides one for a private repository.
Anything that creates a release stays with the forge's own command-line tool.
"""

import json
import os
import urllib.error
import urllib.request
from typing import Any

TIMEOUT = 30.0
_USER_AGENT = "foundata-releasing"


class ForgeError(RuntimeError):
    """The forge could not be reached or answered unexpectedly."""


def _request(url: str) -> Any | None:
    """GET a JSON document, or None when the forge reports it does not exist."""
    headers = {"Accept": "application/json", "User-Agent": _USER_AGENT}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # The error carries an open response body; release it either way.
        exc.close()
        if exc.code == 404:
            return None
        raise ForgeError(f"{url}: HTTP {exc.code} {exc.reason}") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise ForgeError(f"{url}: {exc}") from exc


def release_exists(forge: Any, tag: str) -> bool:
    """Whether the forge has a release for ``tag``."""
    return _request(forge.release_by_tag_url(tag)) is not None


def latest_release_tag(forge: Any) -> str | None:
    """The tag the forge reports as its latest release, or None when there is none."""
    document = _request(forge.latest_release_url())
    if document is None:
        return None
    tag = document.get("tag_name") if isinstance(document, dict) else None
    if not isinstance(tag, str) or not tag:
        raise ForgeError(f"{forge.name}: latest release has no tag name")
    return tag
