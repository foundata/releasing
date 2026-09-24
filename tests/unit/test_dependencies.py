# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import re
import tomllib
from importlib.metadata import version
from pathlib import Path

import pytest
from markdown_it.rules_block import reference
from markdown_it.rules_inline import html_inline, image, link

from tests import check_markdown
from tests.support import ROOT

GUIDE = "markdown-style-guide.md"


def _declared_parser_range() -> tuple[tuple[int, ...], int]:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = [
        entry
        for entry in project["project"]["dependencies"]
        if entry.startswith("markdown-it-py")
    ]
    assert len(dependencies) == 1
    match = re.fullmatch(r"markdown-it-py>=(\d+(?:\.\d+)*),<(\d+)", dependencies[0])
    assert match is not None, dependencies[0]
    return tuple(int(part) for part in match.group(1).split(".")), int(match.group(2))


def test_installed_parser_satisfies_the_declared_range() -> None:
    lower, upper_major = _declared_parser_range()
    installed = tuple(int(part) for part in version("markdown-it-py").split(".")[:3])
    assert lower <= installed
    assert installed[0] < upper_major


def test_rule_api_used_by_the_adapter_is_present() -> None:
    # The adapter wraps these rules to record source positions; a parser
    # release that renames or removes them must fail here, not in production.
    for rule in (reference, html_inline, image, link):
        assert callable(rule)


def test_package_ships_the_typing_marker() -> None:
    # Without PEP 561's marker a consumer running mypy in strict mode cannot
    # see this package's annotations and reports every import as untyped.
    assert (ROOT / "src" / "releasing" / "py.typed").is_file()


def _guide() -> Path | None:
    """The foundata Markdown guide, if this machine has a copy."""
    directory = os.environ.get("FOUNDATA_GUIDELINES")
    guide = (Path(directory) if directory else ROOT.parent / "guidelines") / GUIDE
    return guide if guide.is_file() else None


def _documented_config(text: str) -> str:
    """The ``.rumdl.toml`` the guide's linting section shows."""
    section = text.index("## Linting and automatic formatting")
    start = text.index("```toml\n", section) + len("```toml\n")
    return text[start : text.index("```\n", start)]


def test_the_markdown_config_is_the_guides() -> None:
    # .rumdl.toml is a copy of the guide's file, which goes stale without a word
    # when the guide moves. Compare byte for byte where the guide is checked out.
    guide = _guide()
    if guide is None:
        pytest.skip(f"no {GUIDE} beside this repository or in FOUNDATA_GUIDELINES")
    documented = _documented_config(guide.read_text(encoding="utf-8"))
    committed = (ROOT / check_markdown.CONFIG).read_text(encoding="utf-8")
    assert committed == documented
