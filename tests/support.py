# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later

import sys
from pathlib import Path

import pytest

from releasing import markdown

TRANSFORMER = markdown
ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
RAW = "https://raw.example/repo/ref"
UI = "https://ui.example/repo/ref"
POSIX_ONLY = pytest.mark.skipif(
    sys.platform == "win32",
    reason="symbolic links, device files, permission bits or a path Windows cannot name",
)

__all__ = [
    "FIXTURES",
    "POSIX_ONLY",
    "RAW",
    "ROOT",
    "TRANSFORMER",
    "UI",
    "captured",
    "prepare",
]


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
        strict=strict,
    )
