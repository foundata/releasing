# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later
"""Command-line entry point: one subcommand per release step."""

import argparse
import difflib
import os
import re
import stat
import sys
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import cast
from urllib.parse import quote

from releasing import markdown

Runner = Callable[[argparse.Namespace], int]


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
        return markdown.url_base(args.raw_base), markdown.url_base(args.ui_base)
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
        markdown.url_base(
            args.raw_base or f"https://raw.githubusercontent.com/{project}/{raw_ref}"
        ),
        markdown.url_base(
            args.ui_base or f"https://github.com/{project}/blob/{ui_ref}"
        ),
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


def _show_diff(path: Path, target: Path, original: str, result: str) -> None:
    if original == result:
        print(f"Unchanged: {path}", file=sys.stderr)
        return
    # Display all input line endings as LF, without changing the actual output.
    for line in difflib.unified_diff(
        markdown.display_lines(original),
        markdown.display_lines(result),
        fromfile=str(path),
        tofile=str(target),
    ):
        sys.stderr.write(line)
        if not line.endswith("\n"):
            sys.stderr.write("\n\\ No newline at end of file\n")


def _add_markdown_prepare(parser: argparse.ArgumentParser) -> None:
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
        "--repo-root",
        type=Path,
        help="also check relative destinations exist inside this local directory",
    )
    parser.add_argument(
        "-s",
        "--simplify",
        action="store_true",
        help="collapse project header and linked Markdown images",
    )
    parser.add_argument(
        "--simplify-badges",
        action="store_true",
        help="replace inline linked Markdown images with text links",
    )
    parser.add_argument(
        "--collapse-header",
        action="store_true",
        help="collapse only the project-readme-header div",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="fail on unresolved paths or unsupported resource attributes",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate and show a diff on stderr without writing any files",
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
    parser.set_defaults(run=_run_markdown_prepare, parser=parser)


def _run_markdown_prepare(args: argparse.Namespace) -> int:
    parser = cast(argparse.ArgumentParser, args.parser)
    if args.dry_run and args.output == "-":
        parser.error("--dry-run cannot be combined with --stdout or --output -")
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
                if args.repo_root is not None:
                    markdown.validate_local_files(
                        text,
                        repo_root=args.repo_root,
                        source_path=args.source_path or "README.md",
                    )
                result = markdown.prepare_markdown(
                    text,
                    raw_base=raw_base,
                    ui_base=ui_base,
                    source_path=args.source_path or "README.md",
                    simplify=args.simplify,
                    simplify_badges=args.simplify_badges,
                    collapse_header=args.collapse_header,
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
                if not target.parent.is_dir():
                    raise ValueError(
                        f"output parent must be a directory: {target.parent}"
                    )
            mode = stat.S_IMODE(
                (target if target.exists() and args.output != "-" else path)
                .stat()
                .st_mode
            )
            prepared.append((path, target, text, result, mode))
        # Finish validation for the whole batch before replacing any input.
        for path, target, original_text, result, mode in prepared:
            if args.dry_run:
                _show_diff(path, target, original_text, result)
            elif args.output == "-":
                sys.stdout.buffer.write(result.encode("utf-8"))
                sys.stdout.buffer.flush()
            elif args.output is not None or result != original_text:
                _write(target, result.encode("utf-8"), mode)
                if args.output is None:
                    _show_diff(path, target, original_text, result)
            elif args.output is None:
                print(f"Unchanged: {path}", file=sys.stderr)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the `release` parser with every subcommand registered."""
    parser = argparse.ArgumentParser(
        prog="release", description="Prepare, check and verify software releases."
    )
    commands = parser.add_subparsers(
        dest="command", required=True, metavar="COMMAND", title="commands"
    )
    markdown_parser = commands.add_parser(
        "markdown", help="prepare Markdown for package indexes"
    )
    markdown_commands = markdown_parser.add_subparsers(
        dest="subcommand", required=True, metavar="SUBCOMMAND", title="subcommands"
    )
    _add_markdown_prepare(
        markdown_commands.add_parser(
            "prepare",
            help="rewrite relative destinations to absolute URLs",
            description=markdown.__doc__,
        )
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the non-interactive CLI; reserve stdout for generated output."""
    args = build_parser().parse_args(argv)
    return cast(Runner, args.run)(args)
