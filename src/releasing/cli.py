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
from datetime import date
from pathlib import Path
from typing import cast
from urllib.parse import quote

from releasing import (
    antsibull,
    artifacts,
    attribution,
    build,
    changelog,
    config,
    forge_api,
    forge_release,
    forges,
    markdown,
    processes,
    reporting,
    version,
)
from releasing import (
    publish as uploading,
)
from releasing import (
    push as publication,
)
from releasing import (
    status as reports,
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
        temporary.replace(path)
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
        reporting.detail(line)
        if not line.endswith("\n"):
            reporting.detail("\n\\ No newline at end of file\n")


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
                reporting.phase(f"Kept {path} unchanged")
    except (OSError, UnicodeError, ValueError) as exc:
        reporting.error(str(exc))
        return 1
    return 0


def _run_config_check(args: argparse.Namespace) -> int:
    try:
        loaded = config.load_release_config(cast(Path, args.project))
    except config.ConfigError as exc:
        reporting.error(str(exc))
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


# A read-only query must not hang the command line on an unresponsive
# repository; it is short and local.
_QUERY_TIMEOUT = 30.0


def _load_config(args: argparse.Namespace) -> config.ReleaseConfig:
    return config.load_release_config(cast(Path, args.project))


def _git(root: Path, *arguments: str) -> str | None:
    """Run a read-only Git query in ``root``; None when it is not a checkout."""
    if not (root / ".git").exists():
        return None
    return processes.git(root, *arguments, timeout=_QUERY_TIMEOUT)


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
        reporting.error(str(exc))
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
        edits = version.bump(loaded.root, loaded, args.version, dry_run=args.dry_run)
        for edit in edits:
            reporting.detail(
                "".join(
                    difflib.unified_diff(
                        edit.before.splitlines(keepends=True),
                        edit.after.splitlines(keepends=True),
                        fromfile=f"a/{edit.file}",
                        tofile=f"b/{edit.file}",
                    )
                )
            )
        if (loaded.root / "uv.lock").is_file() and not args.no_lock:
            if args.dry_run:
                reporting.command(["uv", "lock"], executed=False)
                return 0
            processes.run(
                [str(processes.executable("uv")), "lock"],
                cwd=loaded.root,
                stream=True,
                echo=True,
            )
    except (config.ConfigError, version.VersionError, ValueError) as exc:
        reporting.error(str(exc))
        return 1
    except processes.ProcessError as exc:
        reporting.error(f"uv lock failed: {exc}")
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
        reporting.error(str(exc))
        return 1
    reporting.phase(f"Checked {loaded.changelog}")
    return 0


def _run_changelog_show(args: argparse.Namespace) -> int:
    try:
        loaded = _load_config(args)
        body = (
            antsibull.notes(loaded.root, args.version)
            if loaded.changelog_format == "antsibull"
            else changelog.show(_read(loaded.root / loaded.changelog), args.version)
        )
    except (config.ConfigError, changelog.ChangelogError, ValueError) as exc:
        reporting.error(str(exc))
        return 1
    sys.stdout.write(body)
    return 0


def _run_changelog_release(args: argparse.Namespace) -> int:
    try:
        loaded = _load_config(args)
        when = date.fromisoformat(args.date) if args.date else None
        if loaded.changelog_format == "antsibull":
            command = [
                str(processes.executable("antsibull-changelog")),
                "release",
                "--version",
                args.version,
            ]
            if when is not None:
                command += ["--date", when.isoformat()]
            if args.dry_run:
                reporting.command(command, cwd=loaded.root, executed=False)
                return 0
            processes.run(command, cwd=loaded.root, stream=True, echo=True)
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
        if args.dry_run:
            reporting.detail(
                "".join(
                    difflib.unified_diff(
                        _read(path).splitlines(keepends=True),
                        result.splitlines(keepends=True),
                        fromfile=f"a/{loaded.changelog}",
                        tofile=f"b/{loaded.changelog}",
                    )
                )
            )
            reporting.phase(f"Would write {loaded.changelog}")
            return 0
        _write(path, result.encode("utf-8"), stat.S_IMODE(path.stat().st_mode))
    except (config.ConfigError, changelog.ChangelogError, ValueError) as exc:
        reporting.error(str(exc))
        return 1
    except processes.ProcessError as exc:
        reporting.error(f"changelog release failed: {exc}")
        return 1
    reporting.phase(f"Released {args.version} in {loaded.changelog}")
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
        reporting.error(str(exc))
        return 1
    if problems:
        reporting.error("artifacts are not publishable:", problems=problems)
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
            if args.dry_run:
                reporting.detail(text)
                reporting.phase(f"Would write {target}")
                return 0
            _write(target, text.encode("utf-8"), 0o644)
            reporting.phase(
                f"Recorded {len(manifest.artifacts)} artifact(s) in {target}"
            )
    except (
        config.ConfigError,
        version.VersionError,
        artifacts.ArtifactError,
        OSError,
        ValueError,
    ) as exc:
        reporting.error(str(exc))
        return 1
    return 0


def _run_artifacts_verify(args: argparse.Namespace) -> int:
    try:
        manifest_path = cast(Path, args.manifest)
        manifest = artifacts.load_manifest(manifest_path)
        directory = cast("Path | None", args.directory) or manifest_path.parent
        problems = artifacts.verify_manifest(manifest, directory)
    except (artifacts.ArtifactError, OSError) as exc:
        reporting.error(str(exc))
        return 1
    if problems:
        reporting.error("files differ from the manifest:", problems=problems)
        return 1
    reporting.phase(f"Matched {len(manifest.artifacts)} artifact(s) to the manifest")
    return 0


def _run_build(args: argparse.Namespace) -> int:
    try:
        result = build.build(
            cast(Path, args.project),
            revision=args.revision,
            out=cast(Path, args.out),
            expect=args.expect,
            allow_local_sources=args.allow_local_sources,
            dry_run=args.dry_run,
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
        reporting.error(str(exc))
        return 1
    for source in result.local_sources:
        reporting.warning(
            f"built with a local dependency source ({source}); "
            "these artifacts must never be uploaded"
        )
    if args.dry_run:
        reporting.phase(
            f"Would build {result.version} from {result.revision[:12]} "
            f"into {result.directory}"
        )
        return 0
    reporting.phase(
        f"Built {result.version} from {result.revision[:12]} in {result.directory}"
    )
    for path in result.files:
        print(path)
    print(result.manifest)
    return 0


_RELEASE_ERRORS = (
    config.ConfigError,
    version.VersionError,
    changelog.ChangelogError,
    artifacts.ArtifactError,
    build.BuildError,
    tagging.TagError,
    publication.PushError,
    uploading.PublishError,
    forge_release.ForgeReleaseError,
    antsibull.AntsibullError,
    verification.VerificationError,
    forge_api.ForgeError,
    processes.ProcessError,
    ValueError,
)


def _run_tag_create(args: argparse.Namespace) -> int:
    try:
        loaded = _load_config(args)
        if _stops_for_attribution(args, loaded, args.revision):
            return 1
        created = tagging.create(
            loaded.root,
            loaded,
            forges.forge_for(loaded),
            args.version,
            revision=args.revision,
            dry_run=args.dry_run,
            manifest=(
                None
                if args.manifest is None
                else artifacts.load_manifest(cast(Path, args.manifest))
            ),
            offline=args.offline,
        )
    except _RELEASE_ERRORS as exc:
        reporting.error(str(exc))
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
        reporting.error(str(exc))
        return 1
    if problems:
        reporting.error("the release tag is not usable:", problems=problems)
        return 1
    reporting.phase(f"Checked {loaded.tag(args.version)}")
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
            dry_run=args.dry_run,
        )
    except _RELEASE_ERRORS as exc:
        reporting.error(str(exc))
        return 1
    what = "Would delete" if args.dry_run else "Deleted"
    reporting.phase(f"{what} {loaded.tag(args.version)} ({', '.join(deleted)})")
    return 0


def _run_verify(args: argparse.Namespace) -> int:
    try:
        loaded = _load_config(args)
        forge = forges.forge_for(loaded)
        manifest = artifacts.load_manifest(cast(Path, args.manifest))
        found = manifest.version or args.version
        if args.version is not None and found != args.version:
            raise ValueError(f"the manifest records {found}, not {args.version}")
        distribution, selected = verification.select_distribution(
            manifest, index=loaded.index, version=found, distribution=args.distribution
        )
        problems = verification.compare_with_manifest(
            selected, verification.index_files(loaded.index, distribution, found)
        )
        if problems:
            raise verification.VerificationError(
                f"{loaded.index} serves other files than were validated:\n  "
                + "\n  ".join(problems)
            )
        reporting.phase(
            f"Verified {loaded.index} serves the validated files for {found}"
        )
        if loaded.index == "pypi" and not args.no_install:
            reported = verification.installed_version(distribution, found)
            if reported != found:
                raise verification.VerificationError(
                    f"an isolated install of {distribution} reports {reported}, not {found}"
                )
            reporting.phase(
                f"Verified an isolated install reports {distribution} {reported}"
            )
        expected = loaded.tag(found)
        latest = verification.latest_tag(forge)
        if latest != expected:
            raise verification.VerificationError(
                f"{loaded.forge} reports {latest or 'no release'} as latest, not {expected}"
            )
        reporting.phase(
            f"Verified {loaded.forge} reports {expected} as the latest release"
        )
    except _RELEASE_ERRORS as exc:
        reporting.error(str(exc))
        return 1
    return 0


def _run_status(args: argparse.Namespace) -> int:
    try:
        loaded = _load_config(args)
        manifest = (
            None
            if args.manifest is None
            else artifacts.load_manifest(cast(Path, args.manifest))
        )
        report = reports.collect(
            loaded.root,
            loaded,
            forges.forge_for(loaded),
            args.version,
            manifest=manifest,
            offline=args.offline,
        )
    except _RELEASE_ERRORS as exc:
        reporting.error(str(exc))
        return 1
    width = max(len(step.name) for step in report.steps)
    for step in report.steps:
        print(f"{step.state:<8} {step.name:<{width}}  {step.detail}")
    if report.complete:
        print(f"{report.tag}: released")
        return 0
    if report.broken:
        print(f"{report.tag}: needs attention, not continuation")
    else:
        print(f"{report.tag}: incomplete")
    return 1


def _run_push(args: argparse.Namespace) -> int:
    try:
        loaded = _load_config(args)
        prepared = publication.plan(
            loaded.root,
            loaded,
            forges.forge_for(loaded),
            args.version,
            remote=args.remote,
        )
        if _stops_for_attribution(
            args,
            loaded,
            prepared.revision,
            _unpushed(loaded.root, prepared.remote, prepared.branch),
        ):
            return 1
        sent = publication.execute(loaded.root, prepared, dry_run=args.dry_run)
    except _RELEASE_ERRORS as exc:
        reporting.error(str(exc))
        return 1
    what = "Would push" if args.dry_run else "Pushed"
    for reference in sent:
        reporting.phase(f"{what} {reference} to {prepared.remote}")
    return 0


def _run_publish(args: argparse.Namespace) -> int:
    try:
        loaded = _load_config(args)
        manifest_path = cast(Path, args.manifest)
        manifest = artifacts.load_manifest(manifest_path)
        prepared = uploading.plan(manifest, manifest_path.parent, index=loaded.index)
        variable = uploading.token_variable(loaded.index)
        if not args.dry_run and not os.environ.get(variable):
            reporting.warning(
                f"{variable} is unset; {loaded.index} may use a configured "
                "credential instead"
            )
        sent = uploading.execute(prepared, dry_run=args.dry_run)
    except _RELEASE_ERRORS as exc:
        reporting.error(str(exc))
        return 1
    what = "Would upload" if args.dry_run else "Uploaded"
    for name in sent:
        reporting.phase(f"{what} {name}")
    published = "Would publish" if args.dry_run else "Published"
    reporting.phase(f"{published} {prepared.version} to {prepared.index}")
    return 0


def _run_forge_release_create(args: argparse.Namespace) -> int:
    try:
        loaded = _load_config(args)
        manifest_path = None if args.manifest is None else cast(Path, args.manifest)
        manifest = (
            None if manifest_path is None else artifacts.load_manifest(manifest_path)
        )
        prepared = forge_release.plan(
            loaded.root,
            loaded,
            forges.forge_for(loaded),
            args.version,
            manifest=manifest,
            manifest_path=manifest_path,
            offline=args.offline,
        )
        if _stops_for_attribution(args, loaded, prepared.tag):
            return 1
        reported = forge_release.execute(loaded.root, prepared, dry_run=args.dry_run)
    except _RELEASE_ERRORS as exc:
        reporting.error(str(exc))
        return 1
    if args.dry_run:
        return 0
    reporting.phase(f"Created the {prepared.forge} release entry for {prepared.tag}")
    for path in prepared.assets:
        reporting.phase(f"Attached {path.name}")
    if reported:
        print(reported)
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


def _add_dry_run(parser: argparse.ArgumentParser, what: str) -> None:
    """Offer a dry run on a command that changes something."""
    parser.add_argument(
        "--dry-run", action="store_true", help=f"report what would happen; {what}"
    )


def _unpushed(root: Path, remote: str, branch: str) -> str:
    """The range of commits the remote does not have yet, if it can be known.

    Before the first push there is no remote-tracking branch, and everything
    reachable would be "unpushed"; the tagged revision alone is checked then.
    """
    reference = f"{remote}/{branch}"
    try:
        processes.git(
            root, "rev-parse", "--verify", "--quiet", f"{reference}^{{commit}}"
        )
    except processes.ProcessError:
        return ""
    return f"{reference}..{branch}"


def _add_allow_tool_attribution(parser: argparse.ArgumentParser) -> None:
    """Offer to publish commits that credit a tool as their author."""
    parser.add_argument(
        "--allow-tool-attribution",
        action="store_true",
        help="publish commits that credit a tool as their author",
    )


def _stops_for_attribution(
    args: argparse.Namespace, loaded: config.ReleaseConfig, *revisions: str
) -> bool:
    """Whether publishing must stop because a commit credits a tool.

    The commits checked are the ones the command would make public, which are
    also the ones whose message can still be amended for nothing.
    """
    commits = attribution.read(loaded.root, [item for item in revisions if item])
    found = attribution.findings(commits, allowed=loaded.allowed_attribution)
    if not found:
        reporting.phase(f"Checked {len(commits)} commit(s) for attribution")
        return False
    if args.allow_tool_attribution:
        reporting.warning(
            f"publishing {len(found)} tool attribution(s); "
            "--allow-tool-attribution was given"
        )
        return False
    affected = len({finding.revision for finding in found})
    reporting.error(
        f"{affected} commit(s) would publish a tool attribution:",
        problems=attribution.describe(found),
        hint=(
            "Amend the message before publishing, or pass "
            "--allow-tool-attribution to publish it as it stands."
        ),
    )
    return True


def _add_quiet(parser: argparse.ArgumentParser) -> None:
    """Accept --quiet here as well as before the command.

    ``SUPPRESS`` keeps the subcommand's default out of the namespace, so
    ``release --quiet tag create`` is not overwritten by the inner parser.
    """
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        default=argparse.SUPPRESS,
        help="print the result only, without narrating the work",
    )


def _accept_quiet_everywhere(parser: argparse.ArgumentParser) -> None:
    """Add --quiet to every command that runs something.

    Walking the tree instead of naming each subparser means a command added
    later cannot forget the flag.
    """
    pending = [parser]
    while pending:
        current = pending.pop()
        groups = [
            action
            for action in current._actions
            if isinstance(action, argparse._SubParsersAction)
        ]
        if not groups:
            if current is not parser:
                _add_quiet(current)
            continue
        for group in groups:
            pending.extend(group.choices.values())


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
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="print the result only, without narrating the work",
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
    _add_dry_run(version_bump, "no file is written")
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
    _add_dry_run(changelog_release, "the changelog is not written")
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
    _add_dry_run(artifacts_manifest, "the manifest is shown, not written")
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
    _add_dry_run(build_parser, "nothing is built and no directory is written")
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
    tag_create.add_argument(
        "--manifest",
        type=Path,
        help="refuse unless the revision is the one these artifacts were built from",
    )
    _add_dry_run(tag_create, "no tag is created")
    _add_allow_tool_attribution(tag_create)
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
    _add_dry_run(tag_delete, "no tag is deleted")
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
    status_parser = commands.add_parser(
        "status",
        help="report which steps of a release are done, pending or broken",
        description=reports.__doc__,
    )
    _add_project(status_parser)
    status_parser.add_argument("version", metavar="X.Y.Z", help="the release version")
    status_parser.add_argument(
        "--manifest",
        type=Path,
        help="the manifest written by release build, for digest comparison",
    )
    status_parser.add_argument(
        "--offline", action="store_true", help="do not query the index or the forge"
    )
    status_parser.set_defaults(run=_run_status)
    push_parser = commands.add_parser(
        "push",
        help="publish the release branch and its tag together",
        description=publication.__doc__,
    )
    _add_project(push_parser)
    push_parser.add_argument("version", metavar="X.Y.Z", help="the release version")
    push_parser.add_argument(
        "--remote",
        default=publication.DEFAULT_REMOTE,
        help=f"where to push (default: {publication.DEFAULT_REMOTE})",
    )
    push_parser.add_argument(
        "--dry-run", action="store_true", help="ask the remote without sending anything"
    )
    _add_allow_tool_attribution(push_parser)
    push_parser.set_defaults(run=_run_push)
    publish_parser = commands.add_parser(
        "publish",
        help="upload exactly the files a manifest names",
        description=uploading.__doc__,
    )
    _add_project(publish_parser)
    publish_parser.add_argument(
        "manifest", type=Path, help="the manifest written by release build"
    )
    publish_parser.add_argument(
        "--dry-run", action="store_true", help="list the files without uploading"
    )
    publish_parser.set_defaults(run=_run_publish)
    forge_parser = commands.add_parser("forge", help="the forge's own release entry")
    forge_commands = forge_parser.add_subparsers(
        dest="subcommand", required=True, metavar="SUBCOMMAND", title="subcommands"
    )
    forge_create = forge_commands.add_parser(
        "release-create",
        help="create the release entry from the changelog and the manifest",
        description=forge_release.__doc__,
    )
    _add_project(forge_create)
    forge_create.add_argument("version", metavar="X.Y.Z", help="the release version")
    forge_create.add_argument(
        "--manifest", type=Path, help="attach these validated files to the entry"
    )
    forge_create.add_argument(
        "--offline", action="store_true", help="do not ask whether a release exists"
    )
    forge_create.add_argument(
        "--dry-run", action="store_true", help="print the command without running it"
    )
    _add_allow_tool_attribution(forge_create)
    forge_create.set_defaults(run=_run_forge_release_create)
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
    _accept_quiet_everywhere(parser)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the non-interactive CLI; reserve stdout for generated output.

    Stdout carries the product, stderr the story: what is being done, every
    command that changes something and every request to a forge. ``--quiet``
    keeps the product and drops the story; errors are never dropped.
    """
    args = build_parser().parse_args(argv)
    run = cast(Runner, args.run)
    if getattr(args, "quiet", False):
        return run(args)
    root = cast("Path | None", getattr(args, "project", None))
    with reporting.to(sys.stderr, root=root):
        return run(args)
