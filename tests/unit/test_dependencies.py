# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import re
import shlex
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


def _invocation(text: str, verb: str) -> list[str]:
    """The arguments of the guide's ``rumdl <verb>`` example, path included."""
    start = text.index(f"rumdl {verb} \\\n")
    lines: list[str] = []
    for line in text[start:].splitlines():
        lines.append(line)
        if not line.rstrip().endswith("\\"):
            break
    joined = " ".join(line.rstrip().rstrip("\\").strip() for line in lines)
    return shlex.split(joined)


def test_the_markdown_gate_runs_what_the_guide_documents() -> None:
    # tests/check_markdown.py carries a copy of the guide's invocation, which
    # silently goes stale when the guide moves. Read the guide where it is
    # checked out and compare, argument for argument.
    guide = _guide()
    if guide is None:
        pytest.skip(f"no {GUIDE} beside this repository or in FOUNDATA_GUIDELINES")
    documented = guide.read_text(encoding="utf-8")
    check = _invocation(documented, "check")
    fmt = _invocation(documented, "fmt")

    # One copy serves both verbs only for as long as the guide keeps them equal.
    assert check[2:] == fmt[2:], "the guide's check and fmt examples differ"
    assert check[-1] == ".", check[-1]
    assert list(check_markdown.RULES) == check[2:-1]
