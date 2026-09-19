# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later

from pathlib import Path

from releasing import markdown as TRANSFORMER

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
RAW = "https://raw.example/repo/ref"
UI = "https://ui.example/repo/ref"

__all__ = ["FIXTURES", "RAW", "ROOT", "TRANSFORMER", "UI", "prepare"]


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
