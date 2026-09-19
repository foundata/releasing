# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later

import re
import tomllib
from importlib.metadata import version

from markdown_it.rules_block import reference
from markdown_it.rules_inline import html_inline, image, link

from tests.support import ROOT


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
