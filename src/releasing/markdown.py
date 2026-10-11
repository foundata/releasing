# SPDX-FileCopyrightText: foundata GmbH <https://foundata.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Prepare repository Markdown for package indexes without reformatting it."""

import html
import posixpath
import re
import stat
from pathlib import Path, PurePosixPath
from urllib.parse import quote, unquote, urlsplit

from releasing._markdown_syntax import Destination as Destination
from releasing._markdown_syntax import Document as Document
from releasing._markdown_syntax import HtmlTag as HtmlTag
from releasing._markdown_syntax import analyze as analyze
from releasing._markdown_syntax import normalize_source as _normalize
from releasing._markdown_syntax import source_lines as _lines

_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


def is_local(value: str) -> bool:
    """Whether a destination is repository-relative, not absolute or an anchor."""
    return _local(value)


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


def _repository_target(value: str, source_path: str) -> tuple[str, str]:
    if value.startswith("/"):
        raise ValueError(
            "root-relative path has no repository origin on the publishing site"
        )
    parsed = urlsplit(value)
    path = unquote(parsed.path, errors="strict")
    if "\\" in path or any(ord(char) < 32 for char in value + path):
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
    return normalized, value[len(parsed.path) :]


def _absolute(value: str, base: str, source_path: str) -> str:
    normalized, suffix = _repository_target(value, source_path)
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


def _raise_problems(text: str, problems: list[tuple[int, str]]) -> None:
    if problems:
        raise ValueError(
            "\n".join(
                f"{_location(text, offset)}: {reason}"
                for offset, reason in sorted(problems)
            )
        )


def validate_local_files(
    text: str, *, repo_root: Path, source_path: str = "README.md"
) -> None:
    """Check relative destinations against an explicit local repository tree.

    This optional filesystem check is separate from the pure transformation.
    Links may name files or directories; images must name regular files. Symlinks
    must resolve inside the root. Queries, fragments and external URLs are not
    checked. Raise ValueError with original source locations for invalid targets.
    """
    source_path = _source_path(source_path)
    try:
        root = repo_root.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValueError(f"cannot resolve repository root {repo_root}: {exc}") from exc
    if not root.is_dir():
        raise ValueError(f"repository root must be a directory: {repo_root}")
    problems = []
    for destination in analyze(text).destinations:
        if not _local(destination.value):
            continue
        try:
            relative, _ = _repository_target(destination.value, source_path)
            target = (root / relative).resolve(strict=True)
            if not target.is_relative_to(root):
                raise ValueError("local target resolves outside the repository root")
            mode = target.stat().st_mode
            if destination.image and not stat.S_ISREG(mode):
                raise ValueError("image target must be a regular file")
            if relative.endswith("/") and not stat.S_ISDIR(mode):
                raise ValueError("target with a trailing slash must be a directory")
            if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                raise ValueError("local target must be a regular file or directory")
        except FileNotFoundError:
            problems.append(
                (
                    destination.start,
                    f"{destination.value!r}: local target does not exist",
                )
            )
        except (OSError, RuntimeError, ValueError) as exc:
            problems.append((destination.start, f"{destination.value!r}: {exc}"))
    _raise_problems(text, problems)


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


def _collapse_header(original: str) -> str:
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


def _header_div(tags: list[HtmlTag], index: int) -> bool:
    tag = tags[index]
    return (
        tag.name == "div"
        and not tag.closing
        and tag.attributes.get("id") == "project-readme-header"
    )


def _echo(tags: list[HtmlTag], index: int) -> bool:
    """Whether a tag is the end tag HTMLParser adds for a self-closing one."""
    tag = tags[index]
    return (
        index > 0
        and tag.closing
        and (tags[index - 1].start, tags[index - 1].end) == (tag.start, tag.end)
    )


def _empty_anchor(tags: list[HtmlTag], index: int) -> bool:
    """Whether an `<a>` without `href` is directly closed, as heading anchors are."""
    tag = tags[index]
    if tag.name != "a" or tag.closing or "href" in tag.attributes:
        return False
    if index + 1 == len(tags):
        return False
    closing = tags[index + 1]
    # A self-closing `<a id="x"/>` arrives as a start and an end tag with one span.
    return (
        closing.name == "a"
        and closing.closing
        and closing.start in {tag.end, tag.start}
    )


def _html_problems(document: Document, *, header: bool) -> list[tuple[int, str]]:
    """Find raw HTML that stripping would leave for the target to show as text.

    Comments, `br` and empty anchors are stripped. The project header is
    accepted when it is collapsed first; its own checks cover its structure.
    """
    problems = [
        (offset, "HTML declaration would be shown as text")
        for offset in document.declarations
    ]
    tags = document.tags
    accepted: set[int] = set()
    for index, tag in enumerate(tags):
        if index in accepted or tag.name == "br" or _echo(tags, index):
            continue
        if _empty_anchor(tags, index):
            accepted.add(index + 1)
            continue
        if header and _header_div(tags, index):
            following = next(
                (
                    number
                    for number in range(index + 1, len(tags))
                    if tags[number].name == "div"
                ),
                None,
            )
            if following is not None and tags[following].closing:
                accepted.add(following)
            continue
        hint = (
            "; collapse the project-readme-header first"
            if _header_div(tags, index)
            else ""
        )
        problems.append(
            (
                tag.start,
                f"<{'/' if tag.closing else ''}{tag.name}> is raw HTML the target "
                f"would show as text{hint}",
            )
        )
    return problems


def _mark(removed: bytearray, start: int, end: int) -> None:
    removed[start:end] = b"\x01" * (end - start)


def _remove_emptied_lines(
    text: str, removed: bytearray, html_blocks: list[tuple[int, int]]
) -> None:
    """Mark whole lines whose only content was removed.

    A removed run between two blank lines takes one of them along. A removed
    HTML block between two text lines leaves one blank line, so the blocks
    around it stay separate; a removed line inside a paragraph just goes.
    """
    lines = []
    start = 0
    while start < len(text):
        end = text.find("\n", start)
        stop = len(text) if end < 0 else end + 1
        lines.append((start, len(text) if end < 0 else end, stop))
        start = stop
    blank = [not text[start:end].strip(" \t") for start, end, _ in lines]
    emptied = [
        not blank[number]
        and all(
            removed[offset] or text[offset] in " \t" for offset in range(start, end)
        )
        for number, (start, end, _) in enumerate(lines)
    ]
    number = 0
    while number < len(lines):
        if not emptied[number]:
            number += 1
            continue
        first = number
        while number < len(lines) and emptied[number]:
            number += 1
        start, stop = lines[first][0], lines[number - 1][2]
        before = first == 0 or blank[first - 1]
        after = number == len(lines) or blank[number]
        if before and after:
            if number < len(lines):
                stop = lines[number][2]
            elif first:
                start = lines[first - 1][0]
        elif not (before or after) and any(
            left <= start < right for left, right in html_blocks
        ):
            stop = lines[number - 1][1]
        _mark(removed, start, stop)


def _strip_html(original: str) -> str:
    """Remove comments, `br` and empty anchors, and the lines they leave empty."""
    text, positions = _normalize(original)
    document = analyze(text)
    removed = bytearray(len(text))
    for start, end in document.comments:
        _mark(removed, start, end)
    tags = document.tags
    breaks = []
    for index, tag in enumerate(tags):
        if tag.name == "br" and not _echo(tags, index):
            breaks.append(tag)
        elif _empty_anchor(tags, index):
            _mark(removed, tag.start, max(tag.end, tags[index + 1].end))

    def neighbour(offset: int, step: int) -> str:
        while 0 <= offset < len(text) and removed[offset]:
            offset += step
        return text[offset] if 0 <= offset < len(text) else "\n"

    spaces = []
    for tag in breaks:
        # A break between two words becomes a space; next to whitespace it goes.
        if neighbour(tag.start - 1, -1) in " \t\n" or neighbour(tag.end, 1) in " \t\n":
            _mark(removed, tag.start, tag.end)
        else:
            spaces.append((tag.start, tag.end))
    _remove_emptied_lines(text, removed, document.html_blocks)
    edits = [
        (positions[start], positions[end], " ")
        for start, end in spaces
        if not any(removed[start:end])
    ]
    start = 0
    while start < len(text):
        if not removed[start]:
            start += 1
            continue
        end = start
        while end < len(text) and removed[end]:
            end += 1
        edits.append((positions[start], positions[end], ""))
        start = end
    output = _apply(original, edits)
    remaining = analyze(output)
    leftover = sorted(remaining.html_blocks + remaining.inline_html)
    if leftover:
        raise ValueError(
            f"{_location(output, leftover[0][0])}: raw HTML remains after stripping"
        )
    return output


def url_base(value: str) -> str:
    """Validate an absolute HTTP(S) URL base and strip its trailing slashes."""
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
    simplify_badges: bool = False,
    collapse_header: bool = False,
    strip_html: bool = False,
    absolute_anchors: bool = False,
    strict: bool = False,
) -> str:
    """Rewrite active destinations without filesystem, Git or network access.

    Strict diagnostics refer to the original source. The source path is relative
    to the repository root and independent of the output file's location.
    Simplify enables both badge simplification and header collapse; either
    operation can also be selected independently. Strip HTML, for a target that
    shows raw HTML as text, removes comments, `br` and empty anchors after the
    header collapse and refuses any other raw HTML, with or without strict.
    Absolute anchors points in-page `#anchor` links at the same anchor in the
    document under the UI base, for a target without the document's anchors.
    """
    source_path = _source_path(source_path)
    raw_base, ui_base = url_base(raw_base), url_base(ui_base)
    document = analyze(text)
    problems = list(document.unsupported) if strict else []
    if strip_html:
        problems.extend(_html_problems(document, header=simplify or collapse_header))
    edits = []
    for destination in document.destinations:
        anchor = (
            absolute_anchors
            and not destination.image
            and destination.value.startswith("#")
        )
        if not (_local(destination.value) or anchor):
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
    _raise_problems(text, problems)
    output = _apply(text, edits)
    if simplify or simplify_badges:
        output = _apply(output, analyze(output).image_links)
    if simplify or collapse_header:
        output = _collapse_header(output)
    if strip_html:
        output = _strip_html(output)
    if strict and any(
        _local(destination.value) for destination in analyze(output).destinations
    ):
        raise ValueError("relative destinations survived transformation")
    return output


def display_lines(text: str) -> list[str]:
    """Split text into LF-terminated lines for display, ignoring its line endings."""
    return _lines(_normalize(text)[0])
