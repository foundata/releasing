#!/usr/bin/env python3
"""Prepare Markdown files for release/package renderers."""

from __future__ import annotations

import argparse
import difflib
import html
import os
import re
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path


RAW_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".svg",
    ".gif",
    ".webp",
    ".ico",
    ".zip",
    ".tar",
    ".gz",
    ".bz2",
    ".xz",
    ".mp4",
    ".webm",
    ".pdf",
}


class ImgParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.attrs: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "img" and not self.attrs:
            self.attrs = {name.lower(): value or "" for name, value in attrs}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert relative links to absolute URLs in markdown files."
    )
    parser.add_argument("-b", dest="branch", default="main", help="Branch name")
    parser.add_argument("-o", dest="orgname", default="", help="Organization name")
    parser.add_argument("-r", dest="reponame", default="", help="Repository name")
    parser.add_argument("-a", dest="url_base_raw", default="", help="Raw URL base")
    parser.add_argument("-u", dest="url_base_ui", default="", help="UI URL base")
    parser.add_argument(
        "-s",
        dest="simplify_html",
        action="store_true",
        help="Simplify well-known HTML snippets",
    )
    parser.add_argument("files", nargs="+", help="Markdown files to process")
    return parser.parse_args()


def is_relative_target(target: str) -> bool:
    if not target or any(char.isspace() for char in target):
        return False
    if target.startswith(("/", "#")) or "#" in target:
        return False
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", target):
        return False
    if target.startswith("./"):
        return len(target) > 2 and not target[2:].startswith(("/", "#"))
    return target[0].isalnum()


def strip_dot_slash(target: str) -> str:
    if target.startswith("./"):
        return target[2:]
    return target


def has_raw_extension(target: str) -> bool:
    path = target.split("?", 1)[0].lower()
    return any(path.endswith(extension) for extension in RAW_EXTENSIONS)


def rewrite_target(target: str, base_url: str) -> str:
    return f"{base_url}/{strip_dot_slash(target)}"


def find_closing_bracket(text: str, start: int) -> int:
    depth = 1
    index = start
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return -1


def find_closing_paren(text: str, start: int) -> int:
    depth = 1
    index = start
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return -1


def rewrite_markdown_links(text: str, url_base_raw: str, url_base_ui: str) -> str:
    output: list[str] = []
    index = 0

    while index < len(text):
        is_image = text.startswith("![", index)
        is_link = text[index] == "["
        if not is_image and not is_link:
            output.append(text[index])
            index += 1
            continue

        label_start = index + (2 if is_image else 1)
        label_end = find_closing_bracket(text, label_start)
        if label_end == -1 or label_end + 1 >= len(text) or text[label_end + 1] != "(":
            output.append(text[index])
            index += 1
            continue

        target_start = label_end + 2
        target_end = find_closing_paren(text, target_start)
        if target_end == -1:
            output.append(text[index])
            index += 1
            continue

        target = text[target_start:target_end]
        replacement = None
        if is_relative_target(target):
            if is_image:
                if has_raw_extension(target):
                    replacement = rewrite_target(target, url_base_raw)
            else:
                replacement = rewrite_target(target, url_base_ui)

        if replacement is None:
            output.append(text[index : target_end + 1])
        else:
            output.append(text[index:target_start])
            output.append(replacement)
            output.append(")")
        index = target_end + 1

    return "".join(output)


HTML_ATTR_RE = re.compile(
    r"\b(?P<name>href|src)\s*=\s*(?P<quote>['\"])(?P<target>[^'\"]+)(?P=quote)",
    re.IGNORECASE,
)


def rewrite_html_attrs(text: str, url_base_raw: str, url_base_ui: str) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group("name")
        quote = match.group("quote")
        target = match.group("target")
        if not is_relative_target(target):
            return match.group(0)
        base_url = url_base_raw if name.lower() == "src" else url_base_ui
        return f"{name}={quote}{rewrite_target(target, base_url)}{quote}"

    return HTML_ATTR_RE.sub(replace, text)


LINKED_IMG_RE = re.compile(r"^\[<img\b(?P<img>[^>]*)>\]\((?P<href>[^)]+)\)$", re.IGNORECASE)
MARKDOWN_IMAGE_LINK_RE = re.compile(r"^\[!\[(?P<alt>[^\]]*)\]\([^)]*\)\]\((?P<href>[^)]*)\)$")


def img_attrs(markup: str) -> dict[str, str]:
    parser = ImgParser()
    parser.feed(f"<img{markup}>")
    return parser.attrs


def linked_html_img_to_markdown(line: str) -> str:
    match = LINKED_IMG_RE.match(line)
    if not match:
        return line

    attrs = img_attrs(match.group("img"))
    image = attrs.get("src", "")
    if not image:
        return line

    alt = html.escape(attrs.get("alt", ""), quote=False)
    return f"[![{alt}]({image})]({match.group('href')})"


def markdown_image_link_to_text_link(line: str) -> str:
    match = MARKDOWN_IMAGE_LINK_RE.match(line)
    if not match:
        return line
    return f"[{match.group('alt')}]({match.group('href')})"


def simplify_html(text: str) -> str:
    lines = text.splitlines(keepends=True)
    output: list[str] = []
    in_header = False
    header_parts: list[str] = []

    for original_line in lines:
        newline = "\n" if original_line.endswith("\n") else ""
        line = original_line[:-1] if newline else original_line
        stripped = line.strip()

        if not in_header and re.search(
            r"<div[^>]*\bid=['\"]?project-readme-header['\"]?", stripped, re.IGNORECASE
        ):
            in_header = True
            header_parts = []
            continue

        if in_header and re.search(r"</div>", stripped, re.IGNORECASE):
            in_header = False
            if header_parts:
                output.append(" ".join(header_parts) + newline)
            continue

        if in_header:
            if not stripped or re.match(r"^<br\s*/?>$", stripped, re.IGNORECASE):
                continue
            header_parts.append(markdown_image_link_to_text_link(stripped))
            continue

        output.append(linked_html_img_to_markdown(line) + newline)

    if in_header and header_parts:
        output.append(" ".join(header_parts))

    return "".join(output)


def process_content(
    content: str,
    *,
    url_base_raw: str,
    url_base_ui: str,
    should_simplify_html: bool,
) -> str:
    content = rewrite_html_attrs(content, url_base_raw, url_base_ui)
    content = rewrite_markdown_links(content, url_base_raw, url_base_ui)
    if should_simplify_html:
        content = simplify_html(content)
    return content


def process_file(
    file_path: Path,
    *,
    url_base_raw: str,
    url_base_ui: str,
    should_simplify_html: bool,
) -> bool:
    if not file_path.is_file():
        print(f"Warning: File not found: {file_path}", file=sys.stderr)
        return False

    print(f"Processing: {file_path}")
    original = file_path.read_text(encoding="utf-8")
    processed = process_content(
        original,
        url_base_raw=url_base_raw,
        url_base_ui=url_base_ui,
        should_simplify_html=should_simplify_html,
    )

    if processed != original:
        print()
        print(f"Changes for {file_path}:")
        print("----------------------------------------")
        sys.stdout.writelines(
            difflib.unified_diff(
                original.splitlines(keepends=True),
                processed.splitlines(keepends=True),
                fromfile=str(file_path),
                tofile=str(file_path),
            )
        )
        print("----------------------------------------")
        print()

        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            delete=False,
            dir=str(file_path.parent),
            prefix=f".{file_path.name}.",
        ) as tmpfile:
            tmpfile.write(processed)
            tmp_path = Path(tmpfile.name)
        os.replace(tmp_path, file_path)
    else:
        print(f"No changes needed for {file_path}")

    print(f"Completed: {file_path}")
    return True


def main() -> int:
    args = parse_args()
    cwd = Path.cwd()
    orgname = args.orgname or cwd.parent.name
    reponame = args.reponame or cwd.name
    url_base_raw = (
        args.url_base_raw
        or f"https://raw.githubusercontent.com/{orgname}/{reponame}/refs/heads/{args.branch}"
    )
    url_base_ui = (
        args.url_base_ui
        or f"https://github.com/{orgname}/{reponame}/blob/{args.branch}"
    )

    for file_name in args.files:
        ok = process_file(
            Path(file_name),
            url_base_raw=url_base_raw,
            url_base_ui=url_base_ui,
            should_simplify_html=args.simplify_html,
        )
        if not ok:
            return 1

    print("All files processed successfully")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
