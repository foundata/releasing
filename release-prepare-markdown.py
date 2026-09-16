#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later
# /// script
# requires-python = ">=3.12"
# dependencies = ["markdown-it-py==4.2.0"]
# ///
"""Prepare repository Markdown for package indexes without reformatting it."""

import argparse
import difflib
import html
import os
import posixpath
import re
import stat
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import cast, override
from urllib.parse import quote, unquote, urlsplit

from markdown_it import MarkdownIt
from markdown_it.rules_block import StateBlock, reference
from markdown_it.rules_inline import StateInline, html_inline, image, link
from markdown_it.token import Token

_ATTRIBUTE = re.compile(
    r"(?P<name>[^\s=/>]+)(?:\s*=\s*(?:"
    r'"(?P<double>[^"]*)"|\'(?P<single>[^\']*)\'|(?P<bare>[^\s>]+)))?'
)
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
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


def _normalize(text: str) -> tuple[str, list[int]]:
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


def _lines(text: str) -> list[str]:
    parts = text.split("\n")
    return [part + "\n" for part in parts[:-1]] + ([parts[-1]] if parts[-1] else [])


def _content_map(token: Token, lines: list[str], starts: list[int]) -> list[int]:
    if token.map is None:
        raise ValueError("parsed block has no source location")
    positions: list[int] = []
    for number, content in enumerate(_lines(token.content)):
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
    normalized, original_positions = _normalize(text)
    lines = _lines(normalized)
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


def _local(value: str) -> bool:
    return (
        bool(value) and not value.startswith(("#", "//")) and not _SCHEME.match(value)
    )


def _source_path(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or ".." in path.parts
        or "\\" in value
        or value.endswith("/")
        or str(path) == "."
    ):
        raise ValueError("source path must name a file relative to the repository root")
    return str(path)


def _absolute(value: str, base: str, source_path: str) -> str:
    if value.startswith("/"):
        raise ValueError(
            "root-relative path has no repository origin on the publishing site"
        )
    parsed = urlsplit(value)
    path = unquote(parsed.path, errors="strict")
    if "\\" in path or any(ord(char) < 32 for char in value):
        raise ValueError("unsupported control character or backslash in destination")
    normalized = (
        posixpath.normpath(posixpath.join(posixpath.dirname(source_path), path))
        if path
        else source_path
    )
    if normalized == ".." or normalized.startswith("../") or normalized.startswith("/"):
        raise ValueError("path escapes the repository root")
    normalized = "" if normalized == "." else normalized
    if path.endswith("/") and normalized:
        normalized += "/"
    suffix = value[len(parsed.path) :]
    return (
        base
        + "/"
        + quote(normalized, safe="/-._~")
        + quote(suffix, safe="?#/%=&:+,;@!$'-._~")
    )


def _location(text: str, offset: int) -> str:
    breaks = list(re.finditer(r"\r\n?|\n", text[:offset]))
    beginning = breaks[-1].end() if breaks else 0
    return f"{len(breaks) + 1}:{offset - beginning + 1}"


def _apply(text: str, edits: list[tuple[int, int, str]]) -> str:
    end = len(text)
    parts: list[str] = []
    for start, stop, replacement in sorted(edits, reverse=True):
        if stop > end:
            raise ValueError("overlapping destination edits")
        parts.extend((text[stop:end], replacement))
        end = start
    parts.append(text[:end])
    return "".join(reversed(parts))


def _simplify(text: str) -> str:
    original = _apply(text, analyze(text).image_links)
    text, positions = _normalize(original)
    document = analyze(text)
    edits = []
    for number, tag in enumerate(document.tags):
        if (
            tag.name != "div"
            or tag.closing
            or tag.attributes.get("id") != "project-readme-header"
        ):
            continue
        closing = None
        for candidate in document.tags[number + 1 :]:
            if candidate.name == "div":
                if not candidate.closing:
                    raise ValueError("nested div in project-readme-header")
                closing = candidate
                break
        if closing is None:
            raise ValueError("unclosed project-readme-header")
        start = text.rfind("\n", 0, tag.start) + 1
        end = text.find("\n", closing.end)
        end = len(text) if end < 0 else end + 1
        opening_end = text.find("\n", tag.end)
        closing_start = text.rfind("\n", 0, closing.start) + 1
        if (
            opening_end < 0
            or text[start : tag.start].strip()
            or text[tag.end : opening_end].strip()
            or text[closing_start : closing.start].strip()
            or text[closing.end : end].strip()
        ):
            raise ValueError("project-readme-header tags must be on separate lines")
        if any(start <= left < end for left, _ in document.code_blocks):
            raise ValueError("cannot collapse code blocks in project-readme-header")
        content = text[opening_end + 1 : closing_start]
        if "<!--" in content or re.search(r"`[^`]*\n[^`]*`", content):
            raise ValueError(
                "cannot collapse comments or multiline code in project-readme-header"
            )
        parts = [
            line.strip()
            for line in content.splitlines()
            if line.strip()
            and not re.fullmatch(r"<br\s*/?>", line.strip(), re.IGNORECASE)
        ]
        ending = original[positions[closing.end] : positions[end]]
        newline = (
            "\r\n"
            if ending.endswith("\r\n")
            else "\n"
            if ending.endswith("\n")
            else "\r"
            if ending.endswith("\r")
            else ""
        )
        edits.append(
            (
                positions[start],
                positions[end],
                " ".join(parts) + newline if parts else "",
            )
        )
    return _apply(original, edits)


def _base(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"https", "http"}
        or not parsed.netloc
        or parsed.query
        or parsed.fragment
        or any(char.isspace() for char in value)
    ):
        raise ValueError(
            "URL bases must be absolute HTTP(S) URLs without a query or fragment"
        )
    return value.rstrip("/")


def prepare_markdown(
    text: str,
    *,
    raw_base: str,
    ui_base: str,
    source_path: str = "README.md",
    simplify: bool = False,
    strict: bool = False,
) -> str:
    """Rewrite active destinations without filesystem, Git or network access.

    Strict diagnostics refer to the original source. The source path is relative
    to the repository root and independent of the output file's location.
    """
    source_path = _source_path(source_path)
    raw_base, ui_base = _base(raw_base), _base(ui_base)
    document = analyze(text)
    problems = list(document.unsupported) if strict else []
    edits = []
    for destination in document.destinations:
        if not _local(destination.value):
            continue
        try:
            replacement = _absolute(
                destination.value,
                raw_base if destination.image else ui_base,
                source_path,
            )
        except ValueError as exc:
            if strict:
                problems.append((destination.start, f"{destination.value!r}: {exc}"))
            continue
        if destination.attribute:
            replacement = html.escape(replacement, quote=True)
        edits.append((destination.start, destination.end, replacement))
    if problems:
        raise ValueError(
            "\n".join(
                f"{_location(text, offset)}: {reason}"
                for offset, reason in sorted(problems)
            )
        )
    output = _apply(text, edits)
    if simplify:
        output = _simplify(output)
    if strict and any(
        _local(destination.value) for destination in analyze(output).destinations
    ):
        raise ValueError("relative destinations survived transformation")
    return output


def _ref(value: str) -> str:
    if (
        not value
        or any(char.isspace() or char in "~^:?*[\\" for char in value)
        or ".." in value
        or "@{" in value
        or value.endswith(("/", ".", ".lock"))
        or any(part.startswith(".") or not part for part in value.split("/"))
    ):
        raise ValueError("invalid branch or ref")
    return quote(value, safe="/-._~")


def _url_bases(args: argparse.Namespace) -> tuple[str, str]:
    if args.output is not None and not (
        (args.org and args.repo) or (args.raw_base and args.ui_base)
    ):
        raise ValueError("out-of-place output requires -o and -r, or both -a and -u")
    if args.raw_base and args.ui_base:
        return _base(args.raw_base), _base(args.ui_base)
    org = args.org or Path.cwd().parent.name
    repo = args.repo or Path.cwd().name
    if not org or not repo or any(char in org + repo for char in "/\\?#"):
        raise ValueError(
            "organization and repository must be single URL path components"
        )
    if args.ref is not None:
        if not args.ref.startswith(("refs/heads/", "refs/tags/")) and not re.fullmatch(
            r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", args.ref
        ):
            raise ValueError(
                "--ref requires refs/heads/NAME, refs/tags/NAME, or a full commit SHA"
            )
        ui_ref = raw_ref = _ref(args.ref)
    else:
        ui_ref = _ref(args.branch if args.branch is not None else "main")
        raw_ref = "refs/heads/" + ui_ref
    project = quote(org, safe="") + "/" + quote(repo, safe="")
    return (
        _base(
            args.raw_base or f"https://raw.githubusercontent.com/{project}/{raw_ref}"
        ),
        _base(args.ui_base or f"https://github.com/{project}/blob/{ui_ref}"),
    )


def _write(path: Path, data: bytes, mode: int) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fchmod(stream.fileno(), mode)
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the non-interactive CLI; reserve stdout for generated Markdown."""
    parser = argparse.ArgumentParser(description=__doc__)
    ref = parser.add_mutually_exclusive_group()
    ref.add_argument("-b", "--branch", help="branch name (default: main)")
    ref.add_argument("--ref", help="qualified branch/tag ref or full commit SHA")
    parser.add_argument(
        "-o", "--org", help="organization (in-place default: parent directory name)"
    )
    parser.add_argument(
        "-r", "--repo", help="repository (in-place default: directory name)"
    )
    parser.add_argument("-a", "--raw-base", help="absolute URL base for images")
    parser.add_argument("-u", "--ui-base", help="absolute URL base for links")
    parser.add_argument(
        "--source-path", help="repository-relative input path (default: README.md)"
    )
    parser.add_argument(
        "-s",
        "--simplify",
        action="store_true",
        help="collapse project header and linked Markdown images",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="fail on unresolved paths or unsupported resource attributes",
    )
    output = parser.add_mutually_exclusive_group()
    output.add_argument(
        "--output", metavar="PATH", help="write one output file; - means stdout"
    )
    output.add_argument(
        "--stdout",
        action="store_const",
        const="-",
        dest="output",
        help="write one transformed input to stdout",
    )
    output.add_argument(
        "--in-place", action="store_true", help="replace input files (the default)"
    )
    parser.add_argument(
        "files", nargs="+", type=Path, help="UTF-8 Markdown input files"
    )
    args = parser.parse_args(argv)
    if len(args.files) != 1 and (
        args.output is not None or args.source_path is not None
    ):
        parser.error("--output, --stdout and --source-path require exactly one input")
    try:
        raw_base, ui_base = _url_bases(args)
        prepared = []
        for path in args.files:
            if not path.is_file():
                raise ValueError(f"{path}: input must be a regular file")
            if args.output is None and path.is_symlink():
                raise ValueError(f"{path}: in-place input must not be a symbolic link")
            original = path.read_bytes()
            if original.startswith(b"\xef\xbb\xbf"):
                raise ValueError(f"{path}: UTF-8 byte-order marks are unsupported")
            text = original.decode("utf-8")
            try:
                result = prepare_markdown(
                    text,
                    raw_base=raw_base,
                    ui_base=ui_base,
                    source_path=args.source_path or "README.md",
                    simplify=args.simplify,
                    strict=args.strict,
                )
            except ValueError as exc:
                raise ValueError(f"{path}:{exc}") from exc
            target = path if args.output is None else Path(args.output)
            if args.output not in (None, "-"):
                if (
                    target.is_symlink()
                    or target.resolve() == path.resolve()
                    or (target.exists() and target.samefile(path))
                ):
                    raise ValueError(
                        "output must be a separate regular file, not the input or a symbolic link"
                    )
                if target.exists() and not target.is_file():
                    raise ValueError("output must be a regular file")
            mode = stat.S_IMODE(
                (target if target.exists() and args.output != "-" else path)
                .stat()
                .st_mode
            )
            prepared.append((path, target, text, result, mode))
        # Finish validation for the whole batch before replacing any input.
        for path, target, original_text, result, mode in prepared:
            if args.output == "-":
                sys.stdout.buffer.write(result.encode("utf-8"))
                sys.stdout.buffer.flush()
            elif args.output is not None or result != original_text:
                _write(target, result.encode("utf-8"), mode)
                if args.output is None:
                    sys.stderr.writelines(
                        difflib.unified_diff(
                            original_text.splitlines(keepends=True),
                            result.splitlines(keepends=True),
                            fromfile=str(path),
                            tofile=str(path),
                        )
                    )
            elif args.output is None:
                print(f"Unchanged: {path}", file=sys.stderr)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
