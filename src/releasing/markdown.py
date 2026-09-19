# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
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
    """Whether a destination is repository-relative rather than absolute or an anchor."""
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
    strict: bool = False,
) -> str:
    """Rewrite active destinations without filesystem, Git or network access.

    Strict diagnostics refer to the original source. The source path is relative
    to the repository root and independent of the output file's location.
    Simplify enables both badge simplification and header collapse; either
    operation can also be selected independently.
    """
    source_path = _source_path(source_path)
    raw_base, ui_base = url_base(raw_base), url_base(ui_base)
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
    _raise_problems(text, problems)
    output = _apply(text, edits)
    if simplify or simplify_badges:
        output = _apply(output, analyze(output).image_links)
    if simplify or collapse_header:
        output = _collapse_header(output)
    if strict and any(
        _local(destination.value) for destination in analyze(output).destinations
    ):
        raise ValueError("relative destinations survived transformation")
    return output


def display_lines(text: str) -> list[str]:
    """Split text into LF-terminated lines for display, ignoring its line endings."""
    return _lines(_normalize(text)[0])
