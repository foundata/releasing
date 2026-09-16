# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later

import json
from typing import TypedDict, cast

import pytest

from tests.support import FIXTURES, RAW, TRANSFORMER, UI, prepare


class Case(TypedDict, total=False):
    name: str
    input: str
    expected: str
    source_path: str
    simplify: bool


CASES = cast(
    list[Case], json.loads((FIXTURES / "cases.json").read_text(encoding="utf-8"))
)


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_fixture_output_and_idempotence(case: Case) -> None:
    kwargs = {
        "source_path": case.get("source_path", "README.md"),
        "simplify": case.get("simplify", False),
    }
    actual = prepare(
        case["input"],
        source_path=str(kwargs["source_path"]),
        simplify=bool(kwargs["simplify"]),
    )
    assert actual == case["expected"]
    assert (
        prepare(
            actual,
            source_path=str(kwargs["source_path"]),
            simplify=bool(kwargs["simplify"]),
        )
        == actual
    )


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_preserves_line_endings_and_missing_final_newline(newline: str) -> None:
    source = f"# Title{newline}{newline}[x](./docs.md){newline}[y](./y.md)"
    assert prepare(source) == source.replace("./docs.md", UI + "/docs.md").replace(
        "./y.md", UI + "/y.md"
    )


@pytest.mark.parametrize(
    "target", ["/docs.md", "../outside.md", "%2e%2e/outside.md", "%2foutside.md"]
)
def test_strict_reports_original_location_and_unresolved_destination(
    target: str,
) -> None:
    source = f"First line\n\n[x]({target})\n"
    with pytest.raises(ValueError, match="3:5:"):
        prepare(source)
    assert prepare(source, strict=False) == source


def test_strict_refuses_unsupported_resource_attributes() -> None:
    with pytest.raises(ValueError, match="srcset"):
        prepare('<img srcset="a.png 1x, b.png 2x">')


@pytest.mark.parametrize(
    "source_path", ["../README.md", "/README.md", "docs/", ".", "", "docs\\README.md"]
)
def test_invalid_source_path_is_rejected(source_path: str) -> None:
    with pytest.raises(ValueError, match="source path"):
        prepare("[x](a)", source_path=source_path)


@pytest.mark.parametrize(
    "base",
    [
        "relative/path",
        "ftp://example.org",
        "https://example.org/?q=1",
        "https://example.org/#part",
        "https://example.org/a b",
    ],
)
def test_invalid_base_is_rejected(base: str) -> None:
    with pytest.raises(ValueError, match="URL bases"):
        TRANSFORMER.prepare_markdown("[x](a)", raw_base=RAW, ui_base=base)


def test_url_base_trailing_slash_is_normalized() -> None:
    assert (
        TRANSFORMER.prepare_markdown(
            "[x](a) ![x](a)", raw_base=RAW + "/", ui_base=UI + "/"
        )
        == f"[x]({UI}/a) ![x]({RAW}/a)"
    )


@pytest.mark.parametrize(
    "source",
    [
        '<div id="project-readme-header">\ncontent\n',
        '<div id="project-readme-header">content</div>\n',
        '<div id="project-readme-header">\n<div>\ncontent\n</div>\n</div>\n',
        '<div id="project-readme-header">\n\n```text\n[x](relative)\n```\n\n</div>\n',
    ],
)
def test_simplification_refuses_destructive_header_collapse(source: str) -> None:
    with pytest.raises(ValueError, match="project-readme-header"):
        prepare(source, simplify=True)


def test_duplicate_reference_definitions_and_case_folding() -> None:
    source = "![Logo][LOGO]\n\n[logo]: ./one.svg\n[Logo]: ./two.svg\n"
    assert prepare(source) == source.replace("./one.svg", RAW + "/one.svg").replace(
        "./two.svg", RAW + "/two.svg"
    )


def test_repeated_text_and_list_prefixes_map_to_the_right_locations() -> None:
    source = "- `[x](a)` [x](a)\n- [x](a) and `[x](a)`\n"
    expected = f"- `[x](a)` [x]({UI}/a)\n- [x]({UI}/a) and `[x](a)`\n"
    assert prepare(source) == expected


@pytest.mark.parametrize(
    "source",
    [
        "[empty](<>) [empty2]()\n\n[ref]: <>\n",
        "`code spanning\n[example](./untouched.md)`\n",
        "<!-- multiline\n[x](./untouched.md)\n<img src='./untouched.png'>\n-->\n",
        "[not a link](unclosed\n",
    ],
)
def test_empty_destinations_and_non_links_are_unchanged(source: str) -> None:
    assert prepare(source) == source


def test_unicode_paths_and_empty_query_and_fragment_markers() -> None:
    source = "[unicode](./caf\u00e9.md#r\u00e9sum\u00e9) [fragment](./a.md#) [query](./b.md?)"
    assert (
        prepare(source)
        == f"[unicode]({UI}/caf%C3%A9.md#r%C3%A9sum%C3%A9) [fragment]({UI}/a.md#) [query]({UI}/b.md?)"
    )


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_simplification_preserves_line_endings(newline: str) -> None:
    source = newline.join(
        ['<div id="project-readme-header">', "", "Text", "", "</div>", "", "After", ""]
    )
    assert prepare(source, simplify=True) == newline.join(["Text", "", "After", ""])


def test_unicode_line_separators_remain_literal_content() -> None:
    source = "Text\u2028with\u0085separators [x](./docs.md)\n"
    assert prepare(source) == source.replace("./docs.md", UI + "/docs.md")


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_strict_locations_follow_input_line_endings(newline: str) -> None:
    with pytest.raises(ValueError, match="3:5:"):
        prepare(newline.join(["Title", "", "[x](/root.md)"]))
