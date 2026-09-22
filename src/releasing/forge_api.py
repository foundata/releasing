# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later
"""The small read-only part of a forge API the release steps need.

Two questions only: does a release exist for this tag, and which tag does the
forge report as the latest release. Requests are anonymous and read-only; a
token is used only when the environment provides one for a private repository.
Anything that creates a release stays with the forge's own command-line tool.
"""

import os
from typing import Any

from releasing import fetch


class ForgeError(RuntimeError):
    """The forge could not be reached or answered unexpectedly."""


def _request(url: str) -> Any | None:
    """GET a JSON document, or None when the forge reports it does not exist."""
    headers = {}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        return fetch.get(url, headers=headers)
    except fetch.NotFoundError:
        return None
    except fetch.FetchError as exc:
        raise ForgeError(str(exc)) from exc


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
