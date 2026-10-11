# SPDX-FileCopyrightText: foundata GmbH <https://foundata.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Publish a repository's README as the description of its Quay repositories.

Quay renders the description as Markdown in two web interfaces: the newer one
shows raw HTML as literal text, the older one drops it, and neither gives
headings IDs. The document is therefore prepared with the project header
collapsed, the HTML stripped and in-page links pointed at the same anchor in
the document on the forge, so it reads the same in both. It is read from a Git
revision, never from the working tree, and its relative links are checked
against an export of that revision, so the description and its links name the
same source.

Quay has no command-line tool that owns a session, so the write uses a Quay API
token read from a file only its owner can read: an OAuth application token with
the `repo:write` scope, whose user may write to the repository. The token is
sent only in the Authorization header and never printed. After the write, the
description Quay stores is read back and compared with what was sent.
"""

import difflib
import json
import os
import re
import stat
import sys
import tempfile
import urllib.error
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

from typing_extensions import override

from releasing import fetch, markdown, processes, reporting
from releasing._source_export import export

API_URL = "https://quay.io/api/v1"
MAX_TOKEN_BYTES = 64 * 1024
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
_NAME = re.compile(r"[a-z0-9][a-z0-9._-]*")


class QuayError(RuntimeError):
    """The description cannot be prepared, read or written as asked."""


class _UnansweredError(QuayError):
    """No answer arrived, so a write may or may not have taken effect."""


@dataclass(frozen=True)
class Repository:
    """One Quay repository, named as an image reference names it."""

    host: str
    namespace: str
    name: str

    @override
    def __str__(self) -> str:
        """The name as given: host, namespace and repository."""
        return f"{self.host}/{self.namespace}/{self.name}"

    def api_path(self) -> str:
        """The repository's path below the API URL."""
        return (
            f"/repository/{quote(self.namespace, safe='')}/{quote(self.name, safe='')}"
        )

    def page_url(self) -> str:
        """The repository's page in Quay's web interface."""
        return f"https://{self.host}/repository/{self.namespace}/{self.name}"


@dataclass(frozen=True)
class Description:
    """A prepared description and the revision it was prepared from."""

    revision: str
    source_path: str
    text: str


def api_url(value: str) -> str:
    """Validate a Quay API URL: HTTPS, no credentials, query or fragment."""
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "the Quay API URL must use HTTPS without credentials, query or fragment"
        )
    return value.rstrip("/")


def parse_repository(value: str, api: str) -> Repository:
    """Read ``HOST/NAMESPACE/NAME`` and check that the API serves that host."""
    parts = value.split("/")
    if len(parts) != 3 or not all(_NAME.fullmatch(part) for part in parts[1:]):
        raise ValueError(
            f"{value!r}: name a Quay repository as HOST/NAMESPACE/NAME, "
            "such as quay.io/foundata/example"
        )
    host = parts[0].lower()
    if host != urlsplit(api).netloc.lower():
        raise ValueError(f"{value!r}: the Quay API at {api} does not serve {host}")
    return Repository(host, parts[1], parts[2])


def read_token(path: Path) -> str:
    """Read the API token from a regular file only its owner can read.

    The file must not be a symbolic link and, outside Windows, must belong to
    the current user and grant nothing to group or others. The rules match
    ConClear's, so one file serves both.
    """
    if path.is_symlink():
        raise QuayError(f"the token file {path} must not be a symbolic link")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise QuayError(f"cannot open the token file {path}: {exc.strerror}") from exc
    try:
        status = os.fstat(descriptor)
        if not stat.S_ISREG(status.st_mode):
            raise QuayError(f"the token file {path} is not a regular file")
        if sys.platform != "win32":
            if status.st_uid != os.getuid():
                raise QuayError(f"the token file {path} does not belong to you")
            if stat.S_IMODE(status.st_mode) & 0o077:
                raise QuayError(
                    f"the token file {path} is accessible to others; "
                    "restrict it with chmod 600"
                )
        content = b""
        while len(content) <= MAX_TOKEN_BYTES:
            chunk = os.read(descriptor, MAX_TOKEN_BYTES + 1 - len(content))
            if not chunk:
                break
            content += chunk
    except OSError as exc:
        raise QuayError(f"cannot read the token file {path}: {exc.strerror}") from exc
    finally:
        os.close(descriptor)
    if len(content) > MAX_TOKEN_BYTES:
        raise QuayError(f"the token file {path} is too large for a token")
    try:
        token = content.decode("utf-8").rstrip("\r\n")
    except UnicodeDecodeError as exc:
        raise QuayError(f"the token file {path} is not UTF-8") from exc
    if not token or any(char.isspace() or ord(char) < 32 for char in token):
        raise QuayError(f"the token file {path} does not hold one token")
    return token


def prepare(
    root: Path, *, ref: str, source_path: str, raw_base: str, ui_base: str
) -> Description:
    """Prepare the document at ``ref`` the way Quay renders it.

    The revision is exported, relative destinations are checked against the
    export, and the document is prepared with the header collapsed, HTML
    stripped and absolute anchors, strictly.
    """
    try:
        revision = processes.git(
            root, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}"
        ).strip()
    except processes.ProcessError as exc:
        raise QuayError(f"cannot resolve {ref}: {exc}") from exc
    with tempfile.TemporaryDirectory(prefix="releasing-description-") as value:
        tree = Path(value).resolve()
        export(root, revision, tree)
        try:
            path = (tree / source_path).resolve(strict=True)
            inside = path.is_relative_to(tree) and path.is_file()
            original = path.read_text(encoding="utf-8") if inside else None
        except (OSError, RuntimeError, UnicodeError) as exc:
            raise QuayError(f"cannot read {source_path} at {ref}: {exc}") from exc
        if original is None:
            raise QuayError(f"{source_path} is not a file in {ref}")
        try:
            markdown.validate_local_files(
                original, repo_root=tree, source_path=source_path
            )
            text = markdown.prepare_markdown(
                original,
                raw_base=raw_base,
                ui_base=ui_base,
                source_path=source_path,
                collapse_header=True,
                strip_html=True,
                absolute_anchors=True,
                strict=True,
            )
        except ValueError as exc:
            raise QuayError(f"{source_path}:{exc}") from exc
    reporting.phase(f"Prepared {source_path} at {revision[:12]} for Quay")
    return Description(revision, source_path, text)


def publish(
    description: Description,
    repositories: Sequence[Repository],
    *,
    api: str = API_URL,
    token_file: Path | None,
    dry_run: bool = False,
) -> None:
    """Set the description of each repository and verify what Quay stores.

    A repository that already shows the description is left alone. A dry run
    reads the current descriptions, anonymously without a token file, and
    shows the differences instead of writing.
    """
    token = None if token_file is None else read_token(token_file)
    for repository in repositories:
        url = api + repository.api_path()
        current = _description(url, token)
        if current == description.text:
            reporting.phase(f"Kept the description of {repository}, already current")
            continue
        if dry_run:
            _show_diff(current, description.text, str(repository))
            reporting.phase(f"Would publish the description of {repository}")
            continue
        if token is None:
            raise QuayError("writing a description needs a token file")
        unanswered = None
        try:
            _request("PUT", url, token, {"description": description.text})
        except _UnansweredError as exc:
            # The write may have arrived; what Quay stores decides.
            reporting.phase(f"Checking whether the write to {repository} arrived")
            unanswered = exc
        if _description(url, token) != description.text:
            if unanswered is not None:
                raise QuayError(
                    f"the write to {repository} got no answer, and Quay does not "
                    f"show the new description: {unanswered}"
                ) from unanswered
            raise QuayError(
                f"Quay stores a different description for {repository} than was sent"
            )
        reporting.phase(f"Published the description of {repository}")


def _description(url: str, token: str | None) -> str:
    document = _request("GET", url, token)
    if not isinstance(document, dict) or "description" not in document:
        raise QuayError(f"{url}: Quay's answer carries no description")
    value = document["description"]
    if value is None:
        return ""
    if not isinstance(value, str):
        raise QuayError(f"{url}: Quay's description is not text")
    return value


def _request(
    method: str, url: str, token: str | None, body: object | None = None
) -> Any:
    """Send one request and return its JSON answer, narrating it without the token."""
    headers = {
        "Accept": "application/json",
        "User-Agent": fetch.USER_AGENT,
        "Cache-Control": "no-cache",
    }
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=fetch.TIMEOUT) as response:
            content = response.read(MAX_RESPONSE_BYTES + 1)
            reporting.request(method, url, response.status)
    except urllib.error.HTTPError as exc:
        detail = _detail(exc)
        exc.close()
        reporting.request(method, url, exc.code)
        raise QuayError(_refusal(method, url, exc.code, detail)) from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        reporting.request(method, url, "failed")
        raise _UnansweredError(f"{url}: {exc}") from exc
    if len(content) > MAX_RESPONSE_BYTES:
        raise QuayError(f"{url}: Quay's answer exceeds the size limit")
    try:
        return json.loads(content.decode("utf-8"))
    except ValueError as exc:
        raise QuayError(f"{url}: Quay answered with malformed JSON") from exc


def _detail(error: urllib.error.HTTPError) -> str:
    """The reason Quay gives in an error body, which never holds the token."""
    try:
        document = json.loads(error.read(64 * 1024).decode("utf-8"))
    except (OSError, ValueError):
        return ""
    if not isinstance(document, dict):
        return ""
    for key in ("detail", "error_message", "message"):
        if isinstance(document.get(key), str) and document[key].strip():
            return " ".join(str(document[key]).split())
    return ""


def _refusal(method: str, url: str, code: int, detail: str) -> str:
    reason = f": {detail}" if detail else ""
    if code == 401:
        return (
            f"{url}: Quay did not accept the token (HTTP 401){reason}; it must be "
            "an OAuth application token"
        )
    if code == 403:
        return (
            f"{url}: Quay refused the request (HTTP 403){reason}; the token needs "
            "the repo:write scope and its user write permission on the repository"
        )
    if code == 404:
        return (
            f"{url}: Quay knows no such repository, or the token's user cannot "
            f"see it (HTTP 404){reason}"
        )
    if code == 400 and method == "PUT":
        return (
            f"{url}: Quay refused the description (HTTP 400){reason}; quay.io "
            "checks the description of a repository without tags for spam"
        )
    return f"{url}: HTTP {code}{reason}"


def _show_diff(current: str, prepared: str, name: str) -> None:
    for line in difflib.unified_diff(
        markdown.display_lines(current),
        markdown.display_lines(prepared),
        fromfile=f"{name} (current)",
        tofile=f"{name} (prepared)",
    ):
        reporting.detail(line)
        if not line.endswith("\n"):
            reporting.detail("\n\\ No newline at end of file\n")
