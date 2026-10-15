# SPDX-FileCopyrightText: foundata GmbH <https://foundata.com>
# SPDX-License-Identifier: GPL-3.0-or-later

import io
import json
import sys
import urllib.error
from dataclasses import replace
from email.message import Message
from pathlib import Path
from typing import Any

import pytest
from typing_extensions import override

from releasing import markdown
from releasing.artifacts import AnsibleSanity, Manifest

TRANSFORMER = markdown
ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
RAW = "https://raw.example/repo/ref"
UI = "https://ui.example/repo/ref"
POSIX_ONLY = pytest.mark.skipif(
    sys.platform == "win32",
    reason="symbolic links, device files, permission bits or a path Windows cannot name",
)


def with_sanity(manifest: Manifest) -> Manifest:
    """Attach sample passing evidence to a publication fixture."""
    revision = manifest.source_revision or "a" * 40
    return replace(
        manifest,
        source_revision=revision,
        ansible_sanity=AnsibleSanity(
            revision,
            ("ansible-test-sanity-2.19",),
            {"releasing": "7.0.0", "uv": "uv 0.12.3", "nox": "2026.10.1"},
            {entry.filename: entry.sha256 for entry in manifest.artifacts},
        ),
    )


__all__ = [
    "FIXTURES",
    "POSIX_ONLY",
    "RAW",
    "ROOT",
    "TRANSFORMER",
    "UI",
    "FakeQuay",
    "captured",
    "prepare",
    "write_lf",
]


def write_lf(path: Path, text: str) -> None:
    """Write a fixture file with LF, whatever the platform would prefer.

    Python ends a line with CRLF on Windows, and a fixture written that way
    puts those bytes into the commit a test reads back. What these tests
    assert on is the tool's own behaviour, not the platform's.
    """
    path.write_text(text, encoding="utf-8", newline="\n")


def captured(data: bytes) -> str:
    """Captured output as text, with the platform's line endings as LF.

    A command narrates and prints through Python's text streams, which end a
    line with CRLF on Windows. A test asserts what was said; the paths whose
    exact bytes are the contract are asserted on the bytes instead.
    """
    return data.decode("utf-8").replace("\r\n", "\n")


def prepare(
    text: str,
    *,
    source_path: str = "README.md",
    simplify: bool = False,
    simplify_badges: bool = False,
    collapse_header: bool = False,
    strip_html: bool = False,
    absolute_anchors: bool = False,
    strict: bool = True,
) -> str:
    return TRANSFORMER.prepare_markdown(
        text,
        raw_base=RAW,
        ui_base=UI,
        source_path=source_path,
        simplify=simplify,
        simplify_badges=simplify_badges,
        collapse_header=collapse_header,
        strip_html=strip_html,
        absolute_anchors=absolute_anchors,
        strict=strict,
    )


class _Response(io.BytesIO):
    status = 200

    @override
    def __enter__(self) -> "_Response":
        return self

    @override
    def __exit__(self, *_: object) -> None:
        self.close()


class FakeQuay:
    """A stand-in for ``urllib.request.urlopen`` that serves Quay descriptions.

    Every repository starts with ``initial`` and keeps what is written to it.
    ``refuse`` answers a method with an HTTP error and a JSON body,
    ``unanswered_puts`` drops that many write answers after storing them, and
    ``ignore_writes`` answers writes without storing them.
    """

    def __init__(self, initial: str | None = "old") -> None:
        self.initial = initial
        self.stored: dict[str, str] = {}
        self.requests: list[Any] = []
        self.refuse: dict[str, tuple[int, dict[str, str]]] = {}
        self.unanswered_puts = 0
        self.ignore_writes = False

    def __call__(self, request: Any, timeout: float = 0) -> _Response:
        self.requests.append(request)
        method = request.get_method()
        if method in self.refuse:
            code, body = self.refuse[method]
            raise urllib.error.HTTPError(
                request.full_url,
                code,
                "Refused",
                Message(),
                io.BytesIO(json.dumps(body).encode()),
            )
        if method == "PUT":
            if not self.ignore_writes:
                self.stored[request.full_url] = json.loads(request.data)["description"]
            if self.unanswered_puts:
                self.unanswered_puts -= 1
                raise urllib.error.URLError("timed out")
            return _Response(b'{"success": true}')
        description = self.stored.get(request.full_url, self.initial)
        return _Response(json.dumps({"description": description}).encode())

    def methods(self) -> list[str]:
        """The methods requested so far, in order."""
        return [request.get_method() for request in self.requests]
