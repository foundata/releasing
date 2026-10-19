# SPDX-FileCopyrightText: foundata GmbH <https://foundata.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Check, assign and list stable requirement identifiers in foundata guides."""

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from itertools import pairwise

from markdown_it import MarkdownIt
from markdown_it.token import Token
from typing_extensions import override

from releasing._markdown_syntax import normalize_source

RETIRED_HEADING = "Retired requirement identifiers"
EXCLUDED_HEADINGS = frozenset(
    {
        "Table of contents",
        "Goals and scope",
        "Terminology",
        "Requirement identifiers",
        RETIRED_HEADING,
        "Reasoning",
        "Author information",
    }
)
_KEYWORD = re.compile(r"\b(MUST NOT|MUST|SHOULD NOT|SHOULD|MAY)\b")
_RANK = {"MUST NOT": 3, "MUST": 3, "SHOULD NOT": 2, "SHOULD": 2, "MAY": 1}
_ID = re.compile(r"(?P<prefix>[A-Z]+)(?P<number>[0-9]{4})\Z")
_TOKEN = re.compile(r'\s*`(?P<id>[A-Z]+[0-9]{4})`<a id="(?P<anchor>[^"]*)"></a>\Z')
_MARKER = re.compile(r"^ {0,3}(?:[-+*]|[0-9]+[.)])([ \t]+)")


@dataclass(frozen=True)
class Diagnostic:
    """One source-located error, optionally repairable by assigning an ID."""

    line: int
    message: str
    missing: bool = False


@dataclass(frozen=True)
class Item:
    """One top-level item and the source position at which it can receive an ID."""

    line: int
    text: str
    section: str
    anchor: str
    excluded: bool
    modality: str | None
    identifier: str | None
    identifier_anchor: str | None
    insertion: int
    suffix: str

    @property
    def normative(self) -> bool:
        """Whether the item requires an identifier."""
        return not self.excluded and self.modality is not None

    @property
    def statement(self) -> str:
        """The requirement's Markdown without its identifier token."""
        return _TOKEN.sub("", self.text).strip() if self.identifier else self.text


@dataclass(frozen=True)
class Retired:
    """A retired identifier and its complete explanation."""

    line: int
    identifier: str
    note: str


@dataclass
class Guide:
    """A guide parsed without filesystem, Git or network access."""

    source: str
    items: list[Item] = field(default_factory=list)
    retired: list[Retired] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)


class _Anchors(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.identifiers: list[str] = []

    @override
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self.identifiers.extend(
                value for name, value in attrs if name == "id" and value is not None
            )


def _html_anchors(text: str) -> list[str]:
    parser = _Anchors()
    parser.feed(text)
    return parser.identifiers


def _anchors(inline: Token) -> list[str]:
    return [
        anchor
        for child in inline.children or []
        if child.type == "html_inline"
        for anchor in _html_anchors(child.content)
    ]


def _plain(inline: Token) -> str:
    return "".join(
        child.content if child.type == "text" else " "
        for child in inline.children or []
        if child.type in {"text", "code_inline", "softbreak", "hardbreak", "image"}
    )


def _keyword(inlines: list[Token]) -> str | None:
    found = _KEYWORD.findall(" ".join(_plain(token) for token in inlines))
    return max(found, key=lambda word: _RANK[word]) if found else None


def _text(inlines: list[Token]) -> str:
    return " ".join(
        line.strip() for token in inlines for line in token.content.split("\n")
    )


def _label(inlines: list[Token], guide: Guide) -> tuple[str | None, str | None]:
    assert inlines[0].map is not None
    line = inlines[0].map[0] + 1
    text = _text(inlines)
    match = _TOKEN.search(text)
    anchors = [anchor for token in inlines for anchor in _anchors(token)]
    markers = sum(
        child.type == "code_inline"
        and following.type == "html_inline"
        and bool(_html_anchors(following.content))
        for token in inlines
        for child, following in pairwise(token.children or [])
    )
    last = [
        child
        for child in inlines[-1].children or []
        if child.type != "text" or child.content.strip()
    ]
    # A raw suffix inside a code span is an example, not an active identifier.
    if (
        match
        and match["anchor"] in anchors
        and len(last) >= 3
        and last[-3].type == "code_inline"
        and last[-3].content == match["id"]
    ):
        if (
            markers > 1
            or len(
                [
                    anchor
                    for anchor in anchors
                    if re.fullmatch(r"[A-Za-z]+[0-9]+", anchor)
                ]
            )
            > 1
        ):
            guide.diagnostics.append(
                Diagnostic(line, "multiple identifier anchors on one item")
            )
        return match["id"], match["anchor"]
    if markers or any(re.fullmatch(r"[A-Za-z]+[0-9]+", anchor) for anchor in anchors):
        guide.diagnostics.append(
            Diagnostic(line, "malformed or misplaced requirement identifier")
        )
    return None, None


def _collect_item(
    tokens: list[Token], start: int, guide: Guide, *, excluded: bool
) -> tuple[list[Token], int]:
    direct: list[Token] = []
    level = tokens[start].level
    end = start + 1
    while not (tokens[end].type == "list_item_close" and tokens[end].level == level):
        token = tokens[end]
        if token.type == "inline" and tokens[end - 1].type == "paragraph_open":
            if token.level == level + 2:
                direct.append(token)
            elif not excluded and (_keyword([token]) or _label([token], guide)[0]):
                assert token.map is not None
                guide.diagnostics.append(
                    Diagnostic(
                        token.map[0] + 1,
                        "nested list items or quotations cannot carry requirements",
                    )
                )
        end += 1
    return direct, end


def parse(source: str) -> Guide:
    """Parse CommonMark list items, section policy, lead-ins and retired IDs."""
    if source.startswith("\ufeff"):
        raise ValueError("UTF-8 byte-order marks are unsupported")
    normalized, positions = normalize_source(source)
    lines = normalized.split("\n")
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line) + 1)
    tokens = MarkdownIt("commonmark").parse(normalized)
    guide = Guide(source)
    headings: list[tuple[int, str, str]] = []
    lead_in: str | None = None
    index = 0
    while index < len(tokens):
        token = tokens[index]
        titles = [title for _, title, _ in headings]
        excluded = not any(level == 2 for level, _, _ in headings) or bool(
            EXCLUDED_HEADINGS.intersection(titles)
        )
        if token.type == "heading_open" and token.level == 0:
            inline = tokens[index + 1]
            level = int(token.tag[1:])
            title = re.sub(r"<a\b[^>]*>\s*</a>\s*$", "", inline.content).strip()
            anchors = _anchors(inline)
            headings = [heading for heading in headings if heading[0] < level]
            headings.append((level, title, anchors[-1] if anchors else ""))
            lead_in = None
            index += 3
            continue
        if token.type == "list_item_open" and token.level == 1:
            assert token.map is not None
            inlines, end = _collect_item(tokens, index, guide, excluded=excluded)
            if RETIRED_HEADING in titles:
                codes = [
                    child.content
                    for inline in inlines
                    for child in inline.children or []
                    if child.type == "code_inline"
                ]
                if codes:
                    guide.retired.append(
                        Retired(token.map[0] + 1, codes[0], _text(inlines))
                    )
                else:
                    guide.diagnostics.append(
                        Diagnostic(token.map[0] + 1, "retired entry has no identifier")
                    )
            elif inlines:
                identifier, identifier_anchor = _label(inlines, guide)
                last = token.map[1] - 1
                while last > token.map[0] and not lines[last].strip():
                    last -= 1
                insertion = positions[offsets[last] + len(lines[last].rstrip("\n"))]
                assert inlines[-1].map is not None
                suffix = " "
                if inlines[-1].map[1] != last + 1:
                    marker = _MARKER.match(lines[token.map[0]])
                    if marker is None or "\t" in marker[0]:
                        raise ValueError(
                            f"{token.map[0] + 1}: cannot locate list indentation"
                        )
                    newline = (
                        "\r\n"
                        if source[insertion : insertion + 2] == "\r\n"
                        else "\r"
                        if source[insertion : insertion + 1] == "\r"
                        else "\n"
                    )
                    if insertion == len(source) and "\n" in normalized:
                        previous = positions[normalized.rfind("\n")]
                        newline = (
                            "\r\n"
                            if source[previous : previous + 2] == "\r\n"
                            else source[previous]
                        )
                    suffix = newline * 2 + " " * marker.end()
                guide.items.append(
                    Item(
                        line=token.map[0] + 1,
                        text=_text(inlines),
                        section=headings[-1][1] if headings else "",
                        anchor=headings[-1][2] if headings else "",
                        excluded=excluded,
                        modality=_keyword(inlines) or lead_in,
                        identifier=identifier,
                        identifier_anchor=identifier_anchor,
                        insertion=insertion,
                        suffix=suffix,
                    )
                )
            index = end + 1
            continue
        if token.type == "inline" and tokens[index - 1].type == "paragraph_open":
            keyword = _keyword([token])
            if token.level == 1 and keyword and _plain(token).rstrip().endswith(":"):
                lead_in = keyword
            else:
                lead_in = None
                if not excluded and (keyword or _label([token], guide)[0]):
                    assert token.map is not None
                    guide.diagnostics.append(
                        Diagnostic(
                            token.map[0] + 1,
                            "RFC 2119 keyword or identifier outside a top-level list item",
                        )
                    )
        elif token.level == 0 and token.type not in {
            "paragraph_open",
            "paragraph_close",
            "bullet_list_open",
            "ordered_list_open",
        }:
            lead_in = None
        index += 1
    return guide


def validate_prefix(prefix: str) -> str:
    """Require a nonempty uppercase ASCII identifier prefix."""
    if re.fullmatch(r"[A-Z]+", prefix) is None:
        raise ValueError("identifier prefix must contain only uppercase ASCII letters")
    return prefix


def check(guide: Guide, *, prefix: str) -> list[Diagnostic]:
    """Return all errors, including missing, duplicate and retired identifiers."""
    validate_prefix(prefix)
    errors = list(guide.diagnostics)
    retired: dict[str, int] = {}
    for entry in guide.retired:
        match = _ID.fullmatch(entry.identifier)
        if match is None or match["prefix"] != prefix:
            errors.append(
                Diagnostic(
                    entry.line, f"malformed retired identifier {entry.identifier}"
                )
            )
        if entry.identifier in retired:
            errors.append(
                Diagnostic(
                    entry.line, f"duplicate retired identifier {entry.identifier}"
                )
            )
        retired[entry.identifier] = entry.line
    seen: dict[str, int] = {}
    for item in guide.items:
        identifier = item.identifier
        if item.normative and identifier is None:
            errors.append(
                Diagnostic(
                    item.line, "normative list item has no identifier", missing=True
                )
            )
        if identifier is None:
            continue
        if item.excluded:
            errors.append(
                Diagnostic(
                    item.line, f"identifier in non-normative section '{item.section}'"
                )
            )
        elif not item.normative:
            errors.append(
                Diagnostic(
                    item.line,
                    "identifier on an item without RFC 2119 keyword or normative lead-in",
                )
            )
        match = _ID.fullmatch(identifier)
        assert match is not None
        if match["prefix"] != prefix:
            errors.append(
                Diagnostic(
                    item.line, f"identifier {identifier} does not use prefix {prefix}"
                )
            )
        if item.identifier_anchor != identifier.lower():
            errors.append(
                Diagnostic(
                    item.line,
                    f"anchor '{item.identifier_anchor}' does not match {identifier}",
                )
            )
        if identifier in seen:
            errors.append(
                Diagnostic(
                    item.line,
                    f"duplicate identifier {identifier}, first seen at line {seen[identifier]}",
                )
            )
        seen[identifier] = item.line
        if identifier in retired:
            errors.append(
                Diagnostic(item.line, f"retired identifier {identifier} is in use")
            )
    return sorted(errors, key=lambda error: error.line)


def _require_valid(errors: list[Diagnostic]) -> None:
    if errors:
        raise ValueError(
            "\n".join(f"{error.line}: {error.message}" for error in errors)
        )


def assign(guide: Guide, *, prefix: str) -> str:
    """Assign missing IDs above all active and retired IDs, then validate the result."""
    _require_valid(
        [error for error in check(guide, prefix=prefix) if not error.missing]
    )
    used = [item.identifier for item in guide.items if item.identifier]
    used.extend(entry.identifier for entry in guide.retired)
    next_number = (
        max((int(identifier[len(prefix) :]) for identifier in used), default=0) + 1
    )
    missing = [
        item for item in guide.items if item.normative and item.identifier is None
    ]
    if next_number + len(missing) - 1 > 9999:
        raise ValueError("requirement identifier space is exhausted (maximum 9999)")
    result = guide.source
    for number, item in reversed(list(enumerate(missing, start=next_number))):
        identifier = f"{prefix}{number:04d}"
        suffix = f'{item.suffix}`{identifier}`<a id="{identifier.lower()}"></a>'
        result = result[: item.insertion] + suffix + result[item.insertion :]
    _require_valid(check(parse(result), prefix=prefix))
    return result


def listing(guide: Guide, *, prefix: str, name: str) -> dict[str, object]:
    """Return the legacy inventory structure only after successful validation."""
    _require_valid(check(guide, prefix=prefix))
    return {
        "guide": name,
        "requirements": [
            {
                "id": item.identifier,
                "modality": item.modality,
                "section": item.section,
                "anchor": item.anchor,
                "line": item.line,
                "text": item.statement,
            }
            for item in guide.items
            if item.identifier
        ],
        "retired": [
            {"id": entry.identifier, "note": entry.note} for entry in guide.retired
        ],
    }
