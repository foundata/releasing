# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later

import importlib.util
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol, cast

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "release-prepare-markdown.py"
FIXTURES = ROOT / "tests" / "fixtures"
RAW = "https://raw.example/repo/ref"
UI = "https://ui.example/repo/ref"


class Transformer(Protocol):
    def main(self, argv: Sequence[str] | None = None) -> int: ...

    def prepare_markdown(
        self,
        text: str,
        *,
        raw_base: str,
        ui_base: str,
        source_path: str = "README.md",
        simplify: bool = False,
        strict: bool = False,
    ) -> str: ...


def load_script() -> Transformer:
    spec = importlib.util.spec_from_file_location("release_prepare_markdown", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return cast(Transformer, module)


TRANSFORMER = load_script()


def prepare(
    text: str,
    *,
    source_path: str = "README.md",
    simplify: bool = False,
    strict: bool = True,
) -> str:
    return TRANSFORMER.prepare_markdown(
        text,
        raw_base=RAW,
        ui_base=UI,
        source_path=source_path,
        simplify=simplify,
        strict=strict,
    )
