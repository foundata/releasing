# SPDX-FileCopyrightText: foundata GmbH <https://foundata.com>
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


@pytest.mark.parametrize("simplify_badges", [False, True])
@pytest.mark.parametrize("collapse_header", [False, True])
@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_simplification_operations_are_independent(
    simplify_badges: bool, collapse_header: bool, newline: str
) -> None:
    badge = "[![badge](./badge.svg)](./page.md)"
    source = (
        '<div id="project-readme-header">\n\n'
        f"**Project**\n\n{badge}\n<br>\n</div>\n\nOutside {badge}\n"
    )
    output_badge = (
        f"[badge]({UI}/page.md)"
        if simplify_badges
        else f"[![badge]({RAW}/badge.svg)]({UI}/page.md)"
    )
    expected = (
        f"**Project** {output_badge}\n"
        if collapse_header
        else '<div id="project-readme-header">\n\n'
        f"**Project**\n\n{output_badge}\n<br>\n</div>\n"
    ) + f"\nOutside {output_badge}\n"
    source, expected = source.replace("\n", newline), expected.replace("\n", newline)
    assert (
        prepare(
            source,
            simplify_badges=simplify_badges,
            collapse_header=collapse_header,
        )
        == expected
    )
    assert prepare(source, simplify=True) == prepare(
        source, simplify_badges=True, collapse_header=True
    )
    assert prepare(source, simplify=True) == prepare(
        source,
        simplify=True,
        simplify_badges=simplify_badges,
        collapse_header=collapse_header,
    )


def test_badges_only_does_not_attempt_malformed_header_collapse() -> None:
    source = '<div id="project-readme-header">\n\n[![badge](a.svg)](a.md)\n'
    assert prepare(source, simplify_badges=True) == (
        '<div id="project-readme-header">\n\n' + f"[badge]({UI}/a.md)\n"
    )
    with pytest.raises(ValueError, match="unclosed project-readme-header"):
        prepare(source, collapse_header=True)


STRIP_SOURCE = """# Title

<!--
SPDX-FileCopyrightText: Example
-->

Intro [x](./a.md).

<!-- rumdl-disable MD033 -->
<!-- note -->
<div align="center" id="project-readme-header">
<br>

**Star** [![badge](./b.svg)](./c.md)

<br>
</div>
<!-- rumdl-enable MD033 -->


## Usage<a id="usage"></a>

- [Usage](#usage)

<!--REUSE-IgnoreStart-->
<!-- should match -->
Copyright (c) Example <https://example.org>
<!--REUSE-IgnoreEnd-->
"""
STRIP_EXPECTED = f"""# Title

Intro [x]({UI}/a.md).

**Star** [![badge]({RAW}/b.svg)]({UI}/c.md)


## Usage

- [Usage](#usage)

Copyright (c) Example <https://example.org>
"""


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_strip_html_removes_comments_anchors_and_the_collapsed_header(
    newline: str,
) -> None:
    source = STRIP_SOURCE.replace("\n", newline)
    output = prepare(source, collapse_header=True, strip_html=True)
    assert output == STRIP_EXPECTED.replace("\n", newline)
    assert prepare(output, collapse_header=True, strip_html=True) == output


def test_strip_html_is_opt_in() -> None:
    assert "<!--" in prepare(STRIP_SOURCE, collapse_header=True)
    assert '<a id="usage"></a>' in prepare(STRIP_SOURCE, collapse_header=True)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("a<br>b\n", "a b\n"),
        ("a<br/>b<br />c</br>d<BR>e\n", "a b c d e\n"),
        ("a<!-- c --><br>b\n", "a b\n"),
        ("a <br> b\n", "a  b\n"),
        ("a<br>\nb\n", "a\nb\n"),
        ("line one\n<br>\nline two\n", "line one\nline two\n"),
        ("Text\n\n<br>\n\nMore\n", "Text\n\nMore\n"),
        ("| a |\n| - |\n| b<br>c |\n", "| a |\n| - |\n| b c |\n"),
        ("1. Item\n   text.<br>More text\n", "1. Item\n   text. More text\n"),
    ],
)
def test_strip_html_turns_breaks_into_spaces(source: str, expected: str) -> None:
    assert prepare(source, strip_html=True) == expected


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("Para one\n<!-- c -->\nPara two\n", "Para one\n\nPara two\n"),
        ("## Heading\n<!-- c -->\nText\n", "## Heading\n\nText\n"),
        ("a <!-- c --> b\n", "a  b\n"),
        ("a<!---->b<!-- -->c\n", "abc\n"),
        ("Text <!-- x\ny --> more\n", "Text  more\n"),
        ("<!-- c -->\n\n# Title\n", "# Title\n"),
        ("Text\n\n<!-- c -->\n", "Text\n"),
        ("<!-- c -->\n", ""),
        ("Text\n\n<!-- c -->\n\n\n## Next\n", "Text\n\n\n## Next\n"),
        ("- item\n  <!-- c -->\n  more\n", "- item\n\n  more\n"),
        ('## A<a id="a"/>\n', "## A\n"),
        ('## A<a name="a"></a>\n', "## A\n"),
    ],
)
def test_strip_html_keeps_the_blocks_around_removed_lines(
    source: str, expected: str
) -> None:
    assert prepare(source, strip_html=True) == expected


def test_strip_html_leaves_code_alone() -> None:
    source = (
        "`<br>` and `<!-- c -->`\n\n```html\n<!-- c -->\n<div>\n```\n\n"
        '    <a id="x"></a>\n'
    )
    assert prepare(source, strip_html=True) == source


@pytest.mark.parametrize(
    ("source", "location", "message"),
    [
        ('Intro\n\nText <img src="a.png" />\n', "3:6:", "<img> is raw HTML"),
        ('## A<a id="a">text</a>\n', "1:5:", "<a> is raw HTML"),
        ('## A<a id="a">\n', "1:5:", "<a> is raw HTML"),
        ('[x](#a) <a href="#a"></a>\n', "1:9:", "<a> is raw HTML"),
        ("<details>\n<summary>S</summary>\n</details>\n", "1:1:", "<details>"),
        ("Text\n\n<!DOCTYPE html>\n", "3:1:", "declaration"),
        ("<?php echo 1; ?>\n", "1:1:", "declaration"),
        ("<!ELEMENT br EMPTY>\n", "1:1:", "declaration"),
        ("Text <![CDATA[x]]>\n", "1:6:", "declaration"),
        (
            '<div id="project-readme-header">\n\nText\n\n</div>\n',
            "1:1:",
            "collapse the project-readme-header first",
        ),
    ],
)
@pytest.mark.parametrize("strict", [False, True])
def test_strip_html_refuses_other_raw_html_at_its_source_location(
    source: str, location: str, message: str, strict: bool
) -> None:
    with pytest.raises(ValueError, match=f"^{location} [^\n]*{message}"):
        prepare(source, strip_html=True, strict=strict)


def test_strip_html_accepts_the_header_only_when_it_is_collapsed() -> None:
    source = '<div id="project-readme-header">\n<br>\n\n**Star**\n\n</div>\n'
    assert prepare(source, collapse_header=True, strip_html=True) == "**Star**\n"
    assert prepare(source, simplify=True, strip_html=True) == "**Star**\n"


def test_strip_html_fails_when_raw_html_survives() -> None:
    with pytest.raises(ValueError, match=r"^1:1: raw HTML remains after stripping"):
        prepare("<!-- never closed\n\nText\n", strip_html=True)


def test_strip_html_leaves_header_structure_errors_to_the_collapse() -> None:
    with pytest.raises(ValueError, match="unclosed project-readme-header"):
        prepare(
            '<div id="project-readme-header">\n\nText\n',
            collapse_header=True,
            strip_html=True,
        )


def test_absolute_anchors_point_in_page_links_at_the_document() -> None:
    source = (
        "[Usage](#usage) [top](#) ![image](#mark)\n\n"
        '[toc][toc] <a href="#a&amp;b">HTML</a> [elsewhere](./a.md#part)\n\n'
        "[toc]: #toc\n"
    )
    expected = (
        f"[Usage]({UI}/README.md#usage) [top]({UI}/README.md#) ![image](#mark)\n\n"
        f'[toc][toc] <a href="{UI}/README.md#a&amp;b">HTML</a> '
        f"[elsewhere]({UI}/a.md#part)\n\n"
        f"[toc]: {UI}/README.md#toc\n"
    )
    output = prepare(source, absolute_anchors=True)
    assert output == expected
    assert prepare(output, absolute_anchors=True) == output
    assert prepare(source) == source.replace("./a.md", f"{UI}/a.md")


def test_absolute_anchors_follow_the_source_path() -> None:
    assert (
        prepare("[x](#part)\n", source_path="docs/guide.md", absolute_anchors=True)
        == f"[x]({UI}/docs/guide.md#part)\n"
    )


def test_absolute_anchors_with_stripped_html_keep_every_section_reachable() -> None:
    source = (
        '## Table of contents<a id="toc"></a>\n\n- [Usage](#usage)\n\n'
        '## Usage<a id="usage"></a>\n\nBack to the [contents](#toc).\n'
    )
    assert prepare(source, strip_html=True, absolute_anchors=True) == (
        f"## Table of contents\n\n- [Usage]({UI}/README.md#usage)\n\n"
        f"## Usage\n\nBack to the [contents]({UI}/README.md#toc).\n"
    )
