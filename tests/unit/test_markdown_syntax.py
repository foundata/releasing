# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest

from releasing.markdown import Destination, Document, HtmlTag, analyze


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_analysis_records_original_offsets_and_html_attributes(newline: str) -> None:
    markup = '<img src="./logo.svg" height="128">'
    source = newline.join(
        ["Title", "", "- `[guide](./guide.md)` [guide](./guide.md)", markup, ""]
    )
    guide = source.rindex("./guide.md")
    logo = source.index("./logo.svg")
    document = analyze(source)
    assert type(document) is Document
    assert document.destinations == [
        Destination(guide, guide + len("./guide.md"), "./guide.md"),
        Destination(logo, logo + len("./logo.svg"), "./logo.svg", True, True),
    ]
    assert document.tags == [
        HtmlTag(
            source.index(markup),
            source.index(markup) + len(markup),
            "img",
            {"src": "./logo.svg", "height": "128"},
        )
    ]
    assert document.image_links == []
    assert document.unsupported == []
    assert document.code_blocks == []


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_analysis_preserves_reference_order_and_simplification_coordinates(
    newline: str,
) -> None:
    badge = "![badge](./badge.svg)"
    source = newline.join(
        [
            "![logo][logo]",
            "",
            "[logo]: ./logo.svg",
            "",
            f"[{badge}](./page.md)",
            "",
            '<img srcset="small.png 1x">',
            "",
            "```text",
            "[code](./code.md)",
            "```",
            "",
        ]
    )
    document = analyze(source)
    assert [
        (item.start, item.end, item.value, item.image) for item in document.destinations
    ] == [
        (source.index(value), source.index(value) + len(value), value, is_image)
        for value, is_image in [
            ("./logo.svg", True),
            ("./page.md", False),
            ("./badge.svg", True),
        ]
    ]
    assert document.image_links == [
        (source.index(badge), source.index(badge) + len(badge), "badge")
    ]
    assert document.unsupported == [
        (
            source.index("<img"),
            "srcset requires explicit handling; it is outside the supported attribute scope",
        )
    ]
    assert document.code_blocks == [(source.index("```text"), len(source))]


def test_analysis_state_belongs_to_each_document() -> None:
    source = '<img src="./logo.svg">'
    first, second = analyze(source), analyze(source)
    assert first == second
    first.destinations.clear()
    first.tags[0].attributes["src"] = "changed"
    first.tags.clear()
    first.image_links.append((0, 1, "x"))
    first.unsupported.append((0, "unsupported"))
    first.code_blocks.append((0, 1))
    assert second == analyze(source)
    assert analyze("") == Document()
