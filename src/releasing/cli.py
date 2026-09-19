# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later
"""Command-line entry point: one subcommand per release step."""

import argparse
import difflib
import os
import re
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path
from typing import cast
from urllib.parse import quote

from releasing import (
    artifacts,
    build,
    changelog,
    config,
    forge_api,
    forges,
    markdown,
    processes,
    version,
)
from releasing import (
    tag as tagging,
)
from releasing import (
    verify as verification,
)

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


def _run_config_check(args: argparse.Namespace) -> int:
    try:
        loaded = config.load_release_config(cast(Path, args.project))
    except config.ConfigError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"{loaded.source.relative_to(loaded.root)}: valid release declaration")
    print(f"repository: {loaded.repository} ({loaded.forge})")
    print(f"ecosystem: {loaded.ecosystem}, index: {loaded.index}")
    print(f"version files: {', '.join(loaded.version_files) or 'none'}")
    print(f"changelog: {loaded.changelog}")
    print(f"tag: {loaded.tag('X.Y.Z')}")
    for readme in loaded.readmes:
        print(f"readme: {readme.source_path} -> {readme.ref}")
    return 0


def _load_config(args: argparse.Namespace) -> config.ReleaseConfig:
    return config.load_release_config(cast(Path, args.project))


def _git(root: Path, *arguments: str) -> str | None:
    """Run a read-only Git query in ``root``; None when it is not a checkout."""
    if not (root / ".git").exists():
        return None
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *arguments],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError(f"git {arguments[0]} failed in {root}: {exc}") from exc
    return result.stdout


def _run_version_check(args: argparse.Namespace) -> int:
    try:
        loaded = _load_config(args)
        tags = _git(loaded.root, "tag", "--points-at", "HEAD")
        found = version.check(
            loaded.root,
            loaded,
            expect=args.expect,
            tags_on_head=None if tags is None else tags.split(),
        )
        _check_changelog(loaded, found)
    except (
        config.ConfigError,
        version.VersionError,
        changelog.ChangelogError,
        ValueError,
    ) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(found)
    return 0


def _run_version_bump(args: argparse.Namespace) -> int:
    try:
        loaded = _load_config(args)
        touched = [*loaded.version_files, *(pin.file for pin in loaded.dependency_pins)]
        status = _git(loaded.root, "status", "--porcelain", "--", *touched)
        if status and not args.force:
            raise ValueError(
                "uncommitted changes in version files; commit or stash them, "
                "or pass --force:\n" + status.rstrip()
            )
        edits = version.bump(loaded.root, loaded, args.version)
        for edit in edits:
            sys.stdout.writelines(
                difflib.unified_diff(
                    edit.before.splitlines(keepends=True),
                    edit.after.splitlines(keepends=True),
                    fromfile=f"a/{edit.file}",
                    tofile=f"b/{edit.file}",
                )
            )
        if (loaded.root / "uv.lock").is_file() and not args.no_lock:
            print("release: uv lock", file=sys.stderr)
            subprocess.run(["uv", "lock"], cwd=loaded.root, check=True, timeout=600)
    except (config.ConfigError, version.VersionError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"Error: uv lock failed: {exc}", file=sys.stderr)
        return 1
    return 0


def _read(path: Path) -> str:
    try:
        with path.open(encoding="utf-8", newline="") as stream:
            return stream.read()
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc


def _check_changelog(loaded: config.ReleaseConfig, found: str) -> None:
    if loaded.changelog_format == "antsibull":
        text = _read(loaded.root / "changelogs" / "changelog.yaml")
        if not changelog.antsibull_has_release(text, found):
            raise changelog.ChangelogError(
                f"changelogs/changelog.yaml has no release {found}; "
                "run antsibull-changelog release"
            )
        return
    problems = changelog.check(
        _read(loaded.root / loaded.changelog),
        forge=forges.forge_for(loaded),
        tag_format=loaded.tag_format,
        version=found,
    )
    if problems:
        raise changelog.ChangelogError(f"{loaded.changelog}:\n" + "\n".join(problems))


def _run_changelog_check(args: argparse.Namespace) -> int:
    try:
        loaded = _load_config(args)
        if loaded.changelog_format == "antsibull":
            if args.version is None:
                raise ValueError(
                    "antsibull-changelog owns this changelog; pass --version to "
                    "check that a release is recorded"
                )
            _check_changelog(loaded, args.version)
        else:
            problems = changelog.check(
                _read(loaded.root / loaded.changelog),
                forge=forges.forge_for(loaded),
                tag_format=loaded.tag_format,
                version=args.version,
            )
            if problems:
                raise changelog.ChangelogError(
                    f"{loaded.changelog}:\n" + "\n".join(problems)
                )
    except (config.ConfigError, changelog.ChangelogError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"{loaded.changelog}: ok")
    return 0


def _run_changelog_show(args: argparse.Namespace) -> int:
    try:
        loaded = _load_config(args)
        if loaded.changelog_format == "antsibull":
            raise ValueError("antsibull-changelog owns this changelog; nothing to show")
        body = changelog.show(_read(loaded.root / loaded.changelog), args.version)
    except (config.ConfigError, changelog.ChangelogError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    sys.stdout.write(body)
    return 0


def _run_changelog_release(args: argparse.Namespace) -> int:
    try:
        loaded = _load_config(args)
        when = date.fromisoformat(args.date) if args.date else None
        if loaded.changelog_format == "antsibull":
            command = ["antsibull-changelog", "release", "--version", args.version]
            if when is not None:
                command += ["--date", when.isoformat()]
            print("release: " + " ".join(command), file=sys.stderr)
            subprocess.run(command, cwd=loaded.root, check=True, timeout=600)
            return 0
        path = loaded.root / loaded.changelog
        result = changelog.release(
            _read(path),
            args.version,
            forge=forges.forge_for(loaded),
            tag_format=loaded.tag_format,
            when=when,
            placeholder=args.placeholder,
        )
        _write(path, result.encode("utf-8"), stat.S_IMODE(path.stat().st_mode))
    except (config.ConfigError, changelog.ChangelogError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"Error: changelog release failed: {exc}", file=sys.stderr)
        return 1
    print(f"{loaded.changelog}: released {args.version}")
    return 0


def _expected_version(
    args: argparse.Namespace,
) -> tuple[config.ReleaseConfig | None, str]:
    """The version artifacts must carry: --version, else the project's sites."""
    if args.version is not None:
        if not version.is_version(args.version):
            raise ValueError(f"not a version: {args.version!r}")
        return None, args.version
    loaded = _load_config(args)
    return loaded, version.check(loaded.root, loaded)


def _run_artifacts_check(args: argparse.Namespace) -> int:
    try:
        loaded, expected = _expected_version(args)
        inspected = [artifacts.inspect(path) for path in args.files]
        names = (
            ()
            if loaded is None
            else tuple(
                name for name in version.project_names(loaded.root, loaded).values()
            )
        )
        problems = artifacts.check(inspected, version=expected, names=names)
    except (
        config.ConfigError,
        version.VersionError,
        artifacts.ArtifactError,
        ValueError,
    ) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if problems:
        print("Error: artifacts are not publishable:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    for artifact in inspected:
        print(
            f"{artifact.path.name}: {artifact.kind} {artifact.name} {artifact.version}"
        )
    return 0


def _run_artifacts_manifest(args: argparse.Namespace) -> int:
    try:
        loaded, expected = _expected_version(args)
        inspected = [artifacts.inspect(path) for path in args.files]
        problems = artifacts.check(inspected, version=expected)
        if problems:
            raise ValueError(
                "artifacts are not publishable:\n  " + "\n  ".join(problems)
            )
        manifest = artifacts.build_manifest(
            list(args.files),
            repository=args.repository or (loaded.repository if loaded else ""),
            version=expected,
            source_revision=args.revision,
        )
        text = artifacts.dump_manifest(manifest)
        if args.out is None:
            sys.stdout.write(text)
        else:
            target = cast(Path, args.out)
            if target.exists():
                raise ValueError(f"manifest must not already exist: {target}")
            _write(target, text.encode("utf-8"), 0o644)
            print(f"{target}: {len(manifest.artifacts)} artifact(s) recorded")
    except (
        config.ConfigError,
        version.VersionError,
        artifacts.ArtifactError,
        OSError,
        ValueError,
    ) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


def _run_artifacts_verify(args: argparse.Namespace) -> int:
    try:
        manifest_path = cast(Path, args.manifest)
        manifest = artifacts.load_manifest(manifest_path)
        directory = cast("Path | None", args.directory) or manifest_path.parent
        problems = artifacts.verify_manifest(manifest, directory)
    except (artifacts.ArtifactError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if problems:
        print("Error: files differ from the manifest:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    print(f"{len(manifest.artifacts)} artifact(s) match the manifest")
    return 0


def _run_build(args: argparse.Namespace) -> int:
    try:
        result = build.build(
            cast(Path, args.project),
            revision=args.revision,
            out=cast(Path, args.out),
            expect=args.expect,
            allow_local_sources=args.allow_local_sources,
        )
    except (
        config.ConfigError,
        version.VersionError,
        changelog.ChangelogError,
        artifacts.ArtifactError,
        build.BuildError,
        processes.ProcessError,
        ValueError,
    ) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    for source in result.local_sources:
        print(
            f"WARNING: built with a local dependency source ({source}); "
            "these artifacts must never be uploaded",
            file=sys.stderr,
        )
    for prepared in result.prepared:
        print(f"prepared: {prepared}", file=sys.stderr)
    for path in result.files:
        print(path)
    print(result.manifest)
    print(
        f"release: {result.version} from {result.revision[:12]} in {result.directory}",
        file=sys.stderr,
    )
    return 0


_RELEASE_ERRORS = (
    config.ConfigError,
    version.VersionError,
    changelog.ChangelogError,
    artifacts.ArtifactError,
    build.BuildError,
    tagging.TagError,
    verification.VerificationError,
    forge_api.ForgeError,
    processes.ProcessError,
    ValueError,
)


def _run_tag_create(args: argparse.Namespace) -> int:
    try:
        loaded = _load_config(args)
        created = tagging.create(
            loaded.root,
            loaded,
            forges.forge_for(loaded),
            args.version,
            revision=args.revision,
            offline=args.offline,
        )
    except _RELEASE_ERRORS as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(created)
    return 0


def _run_tag_check(args: argparse.Namespace) -> int:
    try:
        loaded = _load_config(args)
        problems = tagging.check(
            loaded.root,
            loaded,
            forges.forge_for(loaded),
            args.version,
            revision=args.revision,
            offline=args.offline,
        )
    except _RELEASE_ERRORS as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if problems:
        print("Error: the release tag is not usable:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    print(f"{loaded.tag(args.version)}: ok")
    return 0


def _run_tag_delete(args: argparse.Namespace) -> int:
    try:
        loaded = _load_config(args)
        deleted = tagging.delete(
            loaded.root,
            loaded,
            forges.forge_for(loaded),
            args.version,
            remote=not args.local,
            offline=args.offline,
        )
    except _RELEASE_ERRORS as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"{loaded.tag(args.version)}: deleted ({', '.join(deleted)})")
    return 0


def _run_verify(args: argparse.Namespace) -> int:
    try:
        loaded = _load_config(args)
        forge = forges.forge_for(loaded)
        manifest = artifacts.load_manifest(cast(Path, args.manifest))
        found = manifest.version or args.version
        if args.version is not None and found != args.version:
            raise ValueError(f"the manifest records {found}, not {args.version}")
        names = sorted(
            {
                entry.filename.split("-")[0].replace("_", "-")
                for entry in manifest.artifacts
            }
        )
        distribution = args.distribution or (names[0] if len(names) == 1 else None)
        if distribution is None:
            raise ValueError(
                "cannot tell which distribution to verify; pass --distribution"
            )
        problems = verification.compare_with_manifest(
            manifest, verification.index_files(loaded.index, distribution, found)
        )
        if problems:
            raise verification.VerificationError(
                f"{loaded.index} serves other files than were validated:\n  "
                + "\n  ".join(problems)
            )
        print(f"{loaded.index}: serves the validated files for {found}")
        if loaded.index == "pypi" and not args.no_install:
            reported = verification.installed_version(distribution, found)
            if reported != found:
                raise verification.VerificationError(
                    f"an isolated install of {distribution} reports {reported}, not {found}"
                )
            print(f"install: {distribution} {reported}")
        expected = loaded.tag(found)
        latest = verification.latest_tag(forge)
        if latest != expected:
            raise verification.VerificationError(
                f"{loaded.forge} reports {latest or 'no release'} as latest, not {expected}"
            )
        print(f"{loaded.forge}: {expected} is the latest release")
    except _RELEASE_ERRORS as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


def _add_artifact_arguments(parser: argparse.ArgumentParser) -> None:
    _add_project(parser)
    parser.add_argument(
        "--version",
        metavar="X.Y.Z",
        help="the version to expect (default: the project's version sites)",
    )
    parser.add_argument(
        "files", nargs="+", type=Path, help="wheels, sdists or collection tarballs"
    )


def _add_tag_arguments(parser: argparse.ArgumentParser) -> None:
    _add_project(parser)
    parser.add_argument("version", metavar="X.Y.Z", help="the release version")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="do not ask the forge whether a release exists",
    )


def _add_project(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--project",
        type=Path,
        default=Path.cwd(),
        help="project root holding pyproject.toml or releasing.toml (default: .)",
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the `release` parser with every subcommand registered."""
    parser = argparse.ArgumentParser(
        prog="release", description="Prepare, check and verify software releases."
    )
    commands = parser.add_subparsers(
        dest="command", required=True, metavar="COMMAND", title="commands"
    )
    config_parser = commands.add_parser(
        "config", help="inspect the release declaration"
    )
    config_commands = config_parser.add_subparsers(
        dest="subcommand", required=True, metavar="SUBCOMMAND", title="subcommands"
    )
    config_check = config_commands.add_parser(
        "check",
        help="validate the declaration and every file it names",
        description=config.__doc__,
    )
    _add_project(config_check)
    config_check.set_defaults(run=_run_config_check)
    version_parser = commands.add_parser(
        "version", help="check or bump every declared version site"
    )
    version_commands = version_parser.add_subparsers(
        dest="subcommand", required=True, metavar="SUBCOMMAND", title="subcommands"
    )
    version_check = version_commands.add_parser(
        "check",
        help="every site, the lockfile, the pins and the tag on HEAD agree",
        description=version.__doc__,
    )
    _add_project(version_check)
    version_check.add_argument(
        "--expect", metavar="X.Y.Z", help="the version the sites must state"
    )
    version_check.set_defaults(run=_run_version_check)
    version_bump = version_commands.add_parser(
        "bump",
        help="rewrite every site and lockstep pin, then run uv lock",
        description="Print a unified diff of every rewritten file to stdout.",
    )
    _add_project(version_bump)
    version_bump.add_argument("version", metavar="X.Y.Z", help="the new version")
    version_bump.add_argument(
        "--force",
        action="store_true",
        help="rewrite version files that have uncommitted changes",
    )
    version_bump.add_argument(
        "--no-lock", action="store_true", help="do not run uv lock afterwards"
    )
    version_bump.set_defaults(run=_run_version_bump)
    changelog_parser = commands.add_parser(
        "changelog", help="check, show or release Keep a Changelog sections"
    )
    changelog_commands = changelog_parser.add_subparsers(
        dest="subcommand", required=True, metavar="SUBCOMMAND", title="subcommands"
    )
    changelog_check = changelog_commands.add_parser(
        "check",
        help="sections, dates, order and link definitions are consistent",
        description=changelog.__doc__,
    )
    _add_project(changelog_check)
    changelog_check.add_argument(
        "--version", metavar="X.Y.Z", help="also require this latest release"
    )
    changelog_check.set_defaults(run=_run_changelog_check)
    changelog_show = changelog_commands.add_parser(
        "show", help="print one version's section, for a release description"
    )
    _add_project(changelog_show)
    changelog_show.add_argument("version", metavar="X.Y.Z", help="or Unreleased")
    changelog_show.set_defaults(run=_run_changelog_show)
    changelog_release = changelog_commands.add_parser(
        "release",
        help="turn the Unreleased entries into a dated version section",
    )
    _add_project(changelog_release)
    changelog_release.add_argument("version", metavar="X.Y.Z", help="the version")
    changelog_release.add_argument(
        "--date", metavar="YYYY-MM-DD", help="release date (default: today)"
    )
    changelog_release.add_argument(
        "--placeholder",
        default=changelog.PLACEHOLDER,
        help="entry for the fresh Unreleased section",
    )
    changelog_release.set_defaults(run=_run_changelog_release)
    artifacts_parser = commands.add_parser(
        "artifacts", help="inspect distributions and record their digests"
    )
    artifacts_commands = artifacts_parser.add_subparsers(
        dest="subcommand", required=True, metavar="SUBCOMMAND", title="subcommands"
    )
    artifacts_check = artifacts_commands.add_parser(
        "check",
        help="version, file names, description links, litter and unsafe members",
        description=artifacts.__doc__,
    )
    _add_artifact_arguments(artifacts_check)
    artifacts_check.set_defaults(run=_run_artifacts_check)
    artifacts_manifest = artifacts_commands.add_parser(
        "manifest", help="check the files and record their SHA-256 digests"
    )
    _add_artifact_arguments(artifacts_manifest)
    artifacts_manifest.add_argument(
        "--out",
        type=Path,
        metavar="PATH",
        help="write the manifest here (default: stdout)",
    )
    artifacts_manifest.add_argument(
        "--revision",
        metavar="SHA",
        help="the source revision the files were built from",
    )
    artifacts_manifest.add_argument(
        "--repository", metavar="OWNER/NAME", help="override the declared repository"
    )
    artifacts_manifest.set_defaults(run=_run_artifacts_manifest)
    artifacts_verify = artifacts_commands.add_parser(
        "verify", help="files beside a manifest match its digests exactly"
    )
    artifacts_verify.add_argument("manifest", type=Path, help="the manifest file")
    artifacts_verify.add_argument(
        "--directory",
        type=Path,
        help="where the files are (default: beside the manifest)",
    )
    artifacts_verify.set_defaults(run=_run_artifacts_verify)
    build_parser = commands.add_parser(
        "build",
        help="build distributions from an exported revision",
        description=build.__doc__,
    )
    _add_project(build_parser)
    build_parser.add_argument(
        "--revision",
        default="HEAD",
        metavar="REV",
        help="what to export (default: HEAD)",
    )
    build_parser.add_argument(
        "--out",
        type=Path,
        required=True,
        metavar="DIR",
        help="new directory for the distributions and their manifest",
    )
    build_parser.add_argument(
        "--expect", metavar="X.Y.Z", help="the version the revision must state"
    )
    build_parser.add_argument(
        "--allow-local-sources",
        action="store_true",
        help="build although a dependency resolves from a local directory",
    )
    build_parser.set_defaults(run=_run_build)
    tag_parser = commands.add_parser(
        "tag", help="create, check or delete a release tag"
    )
    tag_commands = tag_parser.add_subparsers(
        dest="subcommand", required=True, metavar="SUBCOMMAND", title="subcommands"
    )
    tag_create = tag_commands.add_parser(
        "create",
        help="annotated tag on a clean tree whose version sites agree",
        description=tagging.__doc__,
    )
    _add_tag_arguments(tag_create)
    tag_create.add_argument(
        "--revision", default="HEAD", metavar="REV", help="what to tag (default: HEAD)"
    )
    tag_create.set_defaults(run=_run_tag_create)
    tag_check = tag_commands.add_parser(
        "check", help="the tag is annotated, worded and placed as a release tag"
    )
    _add_tag_arguments(tag_check)
    tag_check.add_argument(
        "--revision", default="HEAD", metavar="REV", help="where it must point"
    )
    tag_check.set_defaults(run=_run_tag_check)
    tag_delete = tag_commands.add_parser(
        "delete", help="delete the tag while no release exists for it"
    )
    _add_tag_arguments(tag_delete)
    tag_delete.add_argument(
        "--local", action="store_true", help="do not delete the tag on the remote"
    )
    tag_delete.set_defaults(run=_run_tag_delete)
    verify_parser = commands.add_parser(
        "verify",
        help="the index serves the validated files and the forge reports the tag",
        description=verification.__doc__,
    )
    _add_project(verify_parser)
    verify_parser.add_argument(
        "manifest", type=Path, help="the manifest written by release build"
    )
    verify_parser.add_argument(
        "--version", metavar="X.Y.Z", help="the version the manifest must record"
    )
    verify_parser.add_argument(
        "--distribution", metavar="NAME", help="which distribution to install and query"
    )
    verify_parser.add_argument(
        "--no-install", action="store_true", help="skip the isolated install"
    )
    verify_parser.set_defaults(run=_run_verify)
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
