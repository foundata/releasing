# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest

from tests.support import FIXTURES, RAW, UI, prepare

INLINE_CASES = [
    ("[guide](./docs.md#part)", f"[guide]({UI}/docs.md#part)"),
    ('[guide](<./a b.md> "Title")', f'[guide](<{UI}/a%20b.md> "Title")'),
    ("[`a[b]`](./docs.md)", f"[`a[b]`]({UI}/docs.md)"),
    ("![logo](./logo.svg#mark)", f"![logo]({RAW}/logo.svg#mark)"),
    (
        '[<img src="./shot.avif" height="128">](./docs.md)',
        f'[<img src="{RAW}/shot.avif" height="128">]({UI}/docs.md)',
    ),
]
CONTAINERS = [
    "{content}\n",
    "- {content}\n",
    "> {content}\n",
    "> - parent\n>\n>   1. {content}\n",
    "- parent\n\n  > {content}\n",
    "- [x] {content}\n",
    "| Item |\n| --- |\n| {content} |\n",
]


@pytest.mark.parametrize("original, expected", INLINE_CASES)
@pytest.mark.parametrize("container", CONTAINERS)
@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_active_and_literal_twins_in_nested_containers(
    original: str, expected: str, container: str, newline: str
) -> None:
    literal = f"`` {original} `` <!-- {original} -->"
    source = container.format(content=f"{literal} {original} {literal}")
    output = container.format(content=f"{literal} {expected} {literal}")
    source, output = source.replace("\n", newline), output.replace("\n", newline)
    assert prepare(source) == output
    assert prepare(output) == output
    assert prepare(source, simplify_badges=True) == output


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
@pytest.mark.parametrize("final_newline", [False, True])
def test_mixed_content_fixture_preserves_source_and_is_idempotent(
    newline: str, final_newline: bool
) -> None:
    source = (FIXTURES / "mixed-content.md").read_text(encoding="utf-8")
    expected = (FIXTURES / "mixed-content.expected.md").read_text(encoding="utf-8")
    if not final_newline:
        source, expected = source.rstrip("\n"), expected.rstrip("\n")
    source, expected = source.replace("\n", newline), expected.replace("\n", newline)
    assert prepare(source) == expected
    assert prepare(expected) == expected


@pytest.mark.parametrize("container", CONTAINERS)
def test_badge_simplification_only_changes_active_nested_badges(container: str) -> None:
    badge = "[![logo](./logo.svg)](./docs.md)"
    literal = f"`{badge}` <!-- {badge} -->"
    source = container.format(content=f"{badge} {literal}")
    expected = container.format(content=f"[logo]({UI}/docs.md) {literal}")
    assert prepare(source, simplify_badges=True) == expected
    assert prepare(source, simplify=True) == expected
    assert prepare(expected, simplify_badges=True) == expected
