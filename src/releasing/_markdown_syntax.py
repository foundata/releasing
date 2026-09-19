# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later
"""Map parsed Markdown and HTML syntax to coordinates in the original source."""

import html
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import cast

from markdown_it import MarkdownIt
from markdown_it.rules_block import StateBlock, reference
from markdown_it.rules_inline import StateInline, html_inline, image, link
from markdown_it.token import Token
from typing_extensions import override

_ATTRIBUTE = re.compile(
    r"(?P<name>[^\s=/>]+)(?:\s*=\s*(?:"
    r'"(?P<double>[^"]*)"|\'(?P<single>[^\']*)\'|(?P<bare>[^\s>]+)))?'
)
_SPAN = "prepare_destination"
_LABEL = "prepare_label"
_WHOLE = "prepare_whole"


@dataclass(frozen=True)
class Destination:
    """A parsed destination and its exact coordinates in the original input."""

    start: int
    end: int
    value: str
    image: bool = False
    attribute: bool = False


@dataclass(frozen=True)
class HtmlTag:
    """An HTML tag recognized outside Markdown code and HTML comments."""

    start: int
    end: int
    name: str
    attributes: dict[str, str | None]
    closing: bool = False


@dataclass
class Document:
    """Source coordinates used for destination edits and optional simplification."""

    destinations: list[Destination] = field(default_factory=list)
    tags: list[HtmlTag] = field(default_factory=list)
    image_links: list[tuple[int, int, str]] = field(default_factory=list)
    unsupported: list[tuple[int, str]] = field(default_factory=list)
    code_blocks: list[tuple[int, int]] = field(default_factory=list)


def _capture_inline(
    rule: Callable[[StateInline, bool], bool],
) -> Callable[[StateInline, bool], bool]:
    def capture(state: StateInline, silent: bool) -> bool:
        start, first = state.pos, len(state.tokens)
        if not rule(state, silent):
            return False
        if silent:
            return True
        kind = (
            "image" if rule is image else "link_open" if rule is link else "html_inline"
        )
        token = next(
            token
            for token in state.tokens[first:]
            if token.type == kind and _WHOLE not in token.meta
        )
        token.meta[_WHOLE] = (start, state.pos)
        if rule is html_inline:
            return True
        # Reuse the parser's label and destination grammar, including escapes,
        # balanced parentheses, code spans in labels, titles and references.
        saved = state.pos
        state.pos = start
        bracket = start + (1 if rule is image else 0)
        label_end = state.md.helpers.parseLinkLabel(state, bracket, rule is link)
        state.pos = saved
        token.meta[_LABEL] = (bracket + 1, label_end)
        if (
            "label" not in token.meta
            and state.src[label_end + 1 : label_end + 2] == "("
        ):
            beginning = label_end + 2
            while beginning < state.posMax and state.src[beginning] in " \t\n":
                beginning += 1
            target = state.md.helpers.parseLinkDestination(
                state.src, beginning, state.posMax
            )
            if target.ok:
                angle = state.src[beginning : beginning + 1] == "<"
                token.meta[_SPAN] = (beginning + int(angle), target.pos - int(angle))
        return True

    return capture


def _capture_reference(state: StateBlock, start: int, end: int, silent: bool) -> bool:
    first = len(state.tokens)
    if not reference(state, start, end, silent):
        return False
    if silent:
        return True
    token = next(token for token in state.tokens[first:] if token.type == "definition")
    positions = [
        index
        for line in range(start, state.line)
        for index in range(
            state.bMarks[line] + state.tShift[line],
            min(state.eMarks[line] + 1, len(state.src)),
        )
    ]
    content = "".join(state.src[index] for index in positions)
    beginning = len(str(token.meta["label"])) + 3
    while beginning < len(content) and content[beginning] in " \t\n":
        beginning += 1
    target = state.md.helpers.parseLinkDestination(content, beginning, len(content))
    if not target.ok:
        raise ValueError("cannot locate parsed reference destination")
    angle = content[beginning : beginning + 1] == "<"
    left, right = beginning + int(angle), target.pos - int(angle)
    token.meta[_SPAN] = (
        (positions[left], positions[right - 1] + 1)
        if right > left
        else (positions[left], positions[left])
    )
    return True


def _parser() -> MarkdownIt:
    parser = MarkdownIt(
        "commonmark", {"store_labels": True, "inline_definitions": True}
    )
    parser.inline.ruler.at("link", _capture_inline(link))
    parser.inline.ruler.at("image", _capture_inline(image))
    parser.inline.ruler.at("html_inline", _capture_inline(html_inline))
    parser.block.ruler.at("reference", _capture_reference)
    return parser


def normalize_source(text: str) -> tuple[str, list[int]]:
    """Normalize line endings and map offsets back to the original source."""
    if "\0" in text:
        raise ValueError("NUL characters are unsupported")
    positions = []
    chars = []
    index = 0
    while index < len(text):
        positions.append(index)
        if text[index] == "\r":
            chars.append("\n")
            index += 2 if text[index : index + 2] == "\r\n" else 1
        else:
            chars.append(text[index])
            index += 1
    positions.append(len(text))
    return "".join(chars), positions


def source_lines(text: str) -> list[str]:
    """Split normalized source into lines, retaining LF terminators."""
    parts = text.split("\n")
    return [part + "\n" for part in parts[:-1]] + ([parts[-1]] if parts[-1] else [])


def _content_map(token: Token, lines: list[str], starts: list[int]) -> list[int]:
    if token.map is None:
        raise ValueError("parsed block has no source location")
    positions: list[int] = []
    for number, content in enumerate(source_lines(token.content)):
        line_number = token.map[0] + number
        body = content.removesuffix("\n")
        column = lines[line_number].find(body)
        if column < 0:
            raise ValueError(
                f"cannot map parsed content to input at line {line_number + 1}"
            )
        positions.extend(
            range(
                starts[line_number] + column, starts[line_number] + column + len(body)
            )
        )
        if content.endswith("\n"):
            positions.append(starts[line_number] + len(lines[line_number]) - 1)
    positions.append(positions[-1] + 1 if positions else starts[token.map[0]])
    return positions


class _HtmlDestinations(HTMLParser):
    def __init__(self, content: str, positions: list[int], document: Document) -> None:
        super().__init__(convert_charrefs=True)
        self.positions = positions
        self.document = document
        self.line_starts = [0, *(match.end() for match in re.finditer("\n", content))]
        self.feed(content)

    def _offset(self) -> int:
        line, column = self.getpos()
        return self.line_starts[line - 1] + column

    @override
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        markup = self.get_starttag_text()
        if markup is None:
            raise ValueError("HTML start tag has no source text")
        offset = self._offset()
        self.document.tags.append(
            HtmlTag(
                self.positions[offset],
                self.positions[offset + len(markup)],
                tag,
                dict(attrs),
            )
        )
        name = re.match(r"<[\w:-]+", markup)
        if name is None:
            return
        for match in _ATTRIBUTE.finditer(markup, name.end()):
            attribute = match["name"].lower()
            if attribute == "srcset":
                self.document.unsupported.append(
                    (
                        self.positions[offset],
                        "srcset requires explicit handling; it is outside the supported attribute scope",
                    )
                )
            if attribute not in {"href", "src", "poster"}:
                continue
            for group in ("double", "single", "bare"):
                if match[group] is not None:
                    self.document.destinations.append(
                        Destination(
                            self.positions[offset + match.start(group)],
                            self.positions[offset + match.end(group)],
                            html.unescape(match[group]),
                            attribute != "href",
                            True,
                        )
                    )
                    break

    @override
    def handle_endtag(self, tag: str) -> None:
        offset = self._offset()
        # HTMLParser normalizes tag names, so find the end in the original data.
        end = self.rawdata.find(">", offset) + 1
        self.document.tags.append(
            HtmlTag(self.positions[offset], self.positions[end], tag, {}, True)
        )


def analyze(text: str) -> Document:
    """Parse CommonMark and map active destinations back to unchanged source text."""
    normalized, original_positions = normalize_source(text)
    lines = source_lines(normalized)
    starts = [0, *(match.end() for match in re.finditer("\n", normalized))]
    tokens = _parser().parse(normalized)
    document = Document()
    image_labels = {
        str(child.meta["label"])
        for token in tokens
        for child in token.children or []
        if child.type == "image" and "label" in child.meta
    }
    for token in tokens:
        if token.type in {"fence", "code_block"} and token.map:
            document.code_blocks.append(
                (
                    original_positions[starts[token.map[0]]],
                    original_positions[starts[token.map[1]]]
                    if token.map[1] < len(starts)
                    else len(text),
                )
            )
        if token.type == "definition":
            left, right = cast(tuple[int, int], token.meta[_SPAN])
            document.destinations.append(
                Destination(
                    original_positions[left],
                    original_positions[right],
                    str(token.meta["url"]),
                    str(token.meta["id"]) in image_labels,
                )
            )
        elif token.type in {"inline", "html_block"}:
            children = token.children or []
            if token.type == "inline" and not any(
                child.type in {"image", "link_open", "html_inline"}
                for child in children
            ):
                continue
            positions = [
                original_positions[index]
                for index in _content_map(token, lines, starts)
            ]
            if token.type == "html_block":
                _HtmlDestinations(token.content, positions, document)
                continue
            for child in children:
                if child.type == "html_inline":
                    left, right = cast(tuple[int, int], child.meta[_WHOLE])
                    _HtmlDestinations(
                        child.content, positions[left : right + 1], document
                    )
                elif child.type in {"link_open", "image"} and _SPAN in child.meta:
                    left, right = cast(tuple[int, int], child.meta[_SPAN])
                    value = str(
                        child.attrGet("src" if child.type == "image" else "href") or ""
                    )
                    document.destinations.append(
                        Destination(
                            positions[left],
                            positions[right],
                            value,
                            child.type == "image",
                        )
                    )
            for index, child in enumerate(children):
                if (
                    child.type != "link_open"
                    or _LABEL not in child.meta
                    or "label" in child.meta
                ):
                    continue
                following = children[index + 1 : index + 3]
                if (
                    len(following) != 2
                    or following[0].type != "image"
                    or following[1].type != "link_close"
                    or "label" in following[0].meta
                ):
                    continue
                left, right = cast(tuple[int, int], child.meta[_LABEL])
                image_start, image_end = cast(
                    tuple[int, int], following[0].meta[_WHOLE]
                )
                if (left, right) == (image_start, image_end):
                    alt_start, alt_end = cast(
                        tuple[int, int], following[0].meta[_LABEL]
                    )
                    document.image_links.append(
                        (
                            positions[left],
                            positions[right],
                            text[positions[alt_start] : positions[alt_end]],
                        )
                    )
    return document
