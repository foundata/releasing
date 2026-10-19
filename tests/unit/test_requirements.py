# SPDX-FileCopyrightText: foundata GmbH <https://foundata.com>
# SPDX-License-Identifier: GPL-3.0-or-later

import json

import pytest

from releasing import requirements as req
from tests.support import FIXTURES

HEADER = '## Rules<a id="rules"></a>\n\n'
LABEL = '`IG0001`<a id="ig0001"></a>'


def errors(source: str) -> list[str]:
    return [error.message for error in req.check(req.parse(source), prefix="IG")]


def test_inventory_matches_legacy_fixture() -> None:
    directory = FIXTURES / "requirements"
    guide = req.parse((directory / "guide.md").read_text(encoding="utf-8"))
    assert req.listing(guide, prefix="IG", name="guide.md") == json.loads(
        (directory / "expected.json").read_text(encoding="utf-8")
    )
    assert req.assign(guide, prefix="IG") == guide.source


@pytest.mark.parametrize("ending", ["\n", "\r\n", "\r"])
@pytest.mark.parametrize("final", [False, True])
@pytest.mark.parametrize(
    "tail", ["", "\n  - Explanation.", "\n\n  ```text\n  Example\n  ```"]
)
def test_assignment_preserves_source_and_attaches_to_parent(
    ending: str, final: bool, tail: str
) -> None:
    source = (HEADER + "- You MUST validate." + tail + ("\n" if final else "")).replace(
        "\n", ending
    )
    result = req.assign(req.parse(source), prefix="IG")
    suffix = (ending * 2 + "  " if tail else " ") + LABEL
    insertion = len(source) - (len(ending) if final else 0)
    assert result == source[:insertion] + suffix + source[insertion:]
    parsed = req.parse(result)
    assert req.check(parsed, prefix="IG") == []
    assert len(parsed.items) == 1
    assert parsed.items[0].statement == "You MUST validate."
    assert req.assign(parsed, prefix="IG") == result


def test_assignment_keeps_existing_ids_and_uses_highest_retired_id() -> None:
    source = (
        HEADER + f"- You MUST keep this. {LABEL}\n"
        "- You SHOULD record this.\n"
        "- You MAY add this.\n\n"
        "## Retired requirement identifiers\n\n- `IG0010`: Removed.\n"
    )
    result = req.assign(req.parse(source), prefix="IG")
    assert f"- You MUST keep this. {LABEL}\n" in result
    assert 'record this. `IG0011`<a id="ig0011"></a>' in result
    assert 'add this. `IG0012`<a id="ig0012"></a>' in result


@pytest.mark.parametrize("marker", ["-", "*", "+", "1.", "12)", "  -"])
def test_commonmark_list_markers_and_indentation(marker: str) -> None:
    source = (
        HEADER
        + f"{marker} You MUST validate.\n"
        + " " * (len(marker) + 1)
        + "- Explanation.\n"
    )
    result = req.assign(req.parse(source), prefix="IG")
    assert req.check(req.parse(result), prefix="IG") == []
    assert result.endswith(" " * (len(marker) + 1) + LABEL + "\n")


def test_multiple_paragraphs_belong_to_one_requirement() -> None:
    source = HEADER + "- You MUST validate.\n\n  Further context.\n"
    result = req.assign(req.parse(source), prefix="IG")
    assert result.endswith(f"Further context. {LABEL}\n")
    assert req.parse(result).items[0].statement == "You MUST validate. Further context."


@pytest.mark.parametrize(
    "example",
    [
        "````text\n```\nMUST is an example.\n````\n",
        "~~~text\n```\nMUST is an example.\n~~~\n",
        "    MUST is an indented code example.\n",
        "<!-- MUST is a comment. -->\n",
        "An inline ``example ` MUST`` is literal.\n",
        "A comment <!-- MUST --> is literal.\n",
        "![MUST is alternative text](image.png)\n",
    ],
)
def test_literal_keywords_do_not_create_requirements(example: str) -> None:
    assert errors(HEADER + example) == []


def test_code_examples_of_labels_are_not_identifiers() -> None:
    assert errors(HEADER + "- Example: `` " + LABEL + " ``.\n") == []


def test_lead_in_applies_to_list_but_own_keyword_takes_precedence() -> None:
    source = HEADER + "**You MUST:**\n\n- Validate.\n- You MAY also record.\n"
    result = req.assign(req.parse(source), prefix="IG")
    assert [item.modality for item in req.parse(result).items] == ["MUST", "MAY"]


@pytest.mark.parametrize(
    "separator",
    [
        "Paragraph.\n\n",
        "```text\nexample\n```\n\n",
        "---\n\n",
        "<!-- comment -->\n\n",
        "### Other\n\n",
        "> Quotation.\n\n",
    ],
)
def test_lead_in_does_not_leak_across_blocks(separator: str) -> None:
    source = HEADER + "**You MUST:**\n\n" + separator + "- An explanation.\n"
    guide = req.parse(source)
    assert not guide.items[0].normative
    assert req.assign(guide, prefix="IG") == source


def test_section_exclusion_applies_to_descendants_and_resets() -> None:
    source = (
        "# Guide\n\n- MUST in an introduction.\n\n"
        "## Rules\n\n### Reasoning\n\n#### Detail\n\n- MUST in reasoning.\n\n"
        "### Active<a id='active'></a>\n\n- You MUST validate.\n"
    )
    result = req.assign(req.parse(source), prefix="IG")
    guide = req.parse(result)
    assert [item.identifier for item in guide.items] == [None, None, "IG0001"]
    assert guide.items[-1].anchor == "active"


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("- You MUST validate.\n", "has no identifier"),
        (f"- Explanation. {LABEL}\n", "without RFC 2119"),
        (
            f"- You MUST validate. {LABEL}\n- You MAY record. {LABEL}\n",
            "duplicate identifier",
        ),
        ('- You MUST validate. `IG0001`<a id="wrong"></a>\n', "does not match"),
        ('- You MUST validate. `XX0001`<a id="xx0001"></a>\n', "does not use prefix"),
        ('- You MUST validate. `IG1`<a id="ig1"></a>\n', "malformed or misplaced"),
        ('- You MUST validate. `IG1`<a id="wrong"></a>\n', "malformed or misplaced"),
        (
            f'- You MUST validate. `IG1`<a id="wrong"></a> {LABEL}\n',
            "multiple identifier",
        ),
        (f"- You MUST validate. {LABEL} Extra.\n", "malformed or misplaced"),
        (
            f'- You MUST validate. {LABEL} `IG0002`<a id="ig0002"></a>\n',
            "multiple identifier",
        ),
        ("You MUST validate.\n", "outside a top-level"),
        ("- Explanation.\n  + You MUST validate.\n", "nested list"),
        (f"- Explanation.\n  - You MUST validate. {LABEL}\n", "nested list"),
        (f"## Reasoning\n\n- You MUST validate. {LABEL}\n", "non-normative section"),
        (
            "## Retired requirement identifiers\n\n- `IGG0001`: Removed.\n",
            "malformed retired",
        ),
        (
            "## Retired requirement identifiers\n\n- `IG1`: Removed.\n",
            "malformed retired",
        ),
        ("## Retired requirement identifiers\n\n- Removed.\n", "has no identifier"),
        (
            "## Retired requirement identifiers\n\n- `IG0001`: Removed.\n- `IG0001`: Again.\n",
            "duplicate retired",
        ),
        (
            f"- You MUST validate. {LABEL}\n\n## Retired requirement identifiers\n\n- `IG0001`: Removed.\n",
            "is in use",
        ),
    ],
)
def test_invalid_guides_cannot_be_exported(body: str, message: str) -> None:
    guide = req.parse(HEADER + body)
    assert any(message in error.message for error in req.check(guide, prefix="IG"))
    with pytest.raises(ValueError, match=message):
        req.listing(guide, prefix="IG", name="guide.md")
    if "has no identifier" not in message or "Retired" in body:
        with pytest.raises(ValueError, match=message):
            req.assign(guide, prefix="IG")


def test_retirement_notes_include_continuations() -> None:
    source = "## Retired requirement identifiers\n\n- `IG0001`: Replaced by `IG0002`\n  because the obligation changed.\n"
    listing = req.listing(req.parse(source), prefix="IG", name="guide.md")
    assert listing["retired"] == [
        {
            "id": "IG0001",
            "note": "`IG0001`: Replaced by `IG0002` because the obligation changed.",
        }
    ]


def test_assignment_refuses_identifier_exhaustion() -> None:
    source = HEADER + '- You MUST validate. `IG9999`<a id="ig9999"></a>\n'
    assert req.assign(req.parse(source), prefix="IG") == source
    with pytest.raises(ValueError, match="exhausted"):
        req.assign(req.parse(source + "- You MUST record.\n"), prefix="IG")


@pytest.mark.parametrize("prefix", ["", "ig", "I1", "I-G", "I G", "\u00c4"])
def test_invalid_prefixes_are_rejected(prefix: str) -> None:
    with pytest.raises(ValueError, match="uppercase ASCII"):
        req.assign(req.parse(HEADER), prefix=prefix)


@pytest.mark.parametrize("source", ["\ufeff" + HEADER, HEADER + "\0"])
def test_invalid_source_is_rejected(source: str) -> None:
    with pytest.raises(ValueError):
        req.parse(source)


def test_unicode_line_separator_is_not_a_commonmark_newline() -> None:
    source = HEADER + "- You MUST preserve this\u2028text.\n"
    assert (
        req.assign(req.parse(source), prefix="IG")
        == source.rstrip("\n") + " " + LABEL + "\n"
    )
