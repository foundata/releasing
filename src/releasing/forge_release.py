# SPDX-FileCopyrightText: foundata GmbH <https://foundata.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Create the forge's release entry for a tag, through the forge's own tool.

The notes are the changelog section for that version and the assets are the
manifest's files, so the release entry cannot drift from what was written and
what was validated. The write itself is delegated to the forge's command-line
tool, which already owns an authenticated session. This package never holds a
credential that can write to a repository.
"""

import hashlib
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from releasing import antsibull, artifacts, changelog, forge_api, processes, reporting
from releasing._artifact_staging import Upload, stage
from releasing.artifacts import Manifest
from releasing.config import ReleaseConfig
from releasing.forges import Forge


class ForgeReleaseError(RuntimeError):
    """The release entry cannot be created as asked."""


@dataclass(frozen=True)
class ReleasePlan:
    """What the forge entry would say and carry."""

    forge: str
    tool: str
    repository: str
    tag: str
    revision: str
    title: str
    notes: str
    uploads: tuple[Upload, ...]

    @property
    def assets(self) -> tuple[Path, ...]:
        """The original paths, for reporting and dry runs only."""
        return tuple(item.path for item in self.uploads)


def plan(
    root: Path,
    config: ReleaseConfig,
    forge: Forge,
    version_string: str,
    *,
    manifest: Manifest | None = None,
    manifest_path: Path | None = None,
    offline: bool = False,
) -> ReleasePlan:
    """Assemble the entry from changelog and manifest, and check it can be made."""
    tool = forge.tool
    if tool is None:
        raise ForgeReleaseError(f"no release tool is known for the {forge.name} forge")
    processes.executable(tool)
    tag = config.tag(version_string)
    if not offline and forge_api.release_exists(forge, tag):
        raise ForgeReleaseError(
            f"{forge.name} already has a release for {tag}; a release entry is "
            "created once and the version is spent"
        )
    revision = _tag_revision(root, tag)
    notes = _notes(root, config, version_string, revision)
    uploads: tuple[Upload, ...] = ()
    if manifest is not None and manifest_path is not None:
        manifest_path = manifest_path.absolute()
        if manifest.version and manifest.version != version_string:
            raise ForgeReleaseError(
                f"the manifest records version {manifest.version}, not {version_string}"
            )
        if manifest.repository and manifest.repository != config.repository:
            raise ForgeReleaseError(
                f"the manifest records repository {manifest.repository}, "
                f"not {config.repository}"
            )
        if manifest.source_revision is not None:
            if manifest.source_revision != revision:
                raise ForgeReleaseError(
                    f"the artifacts were built from {manifest.source_revision}, "
                    f"but {tag} names {revision}"
                )
        problems = artifacts.verify_manifest(manifest, manifest_path.parent)
        if problems:
            raise ForgeReleaseError(
                "the files beside the manifest are not the validated set:\n  "
                + "\n  ".join(problems)
            )
        try:
            content = manifest_path.read_bytes()
        except OSError as exc:
            raise ForgeReleaseError(
                f"cannot read manifest {manifest_path}: {exc}"
            ) from exc
        if artifacts.parse_manifest(content, source=str(manifest_path)) != manifest:
            raise ForgeReleaseError("the manifest changed since it was loaded")
        uploads = (
            Upload(manifest_path, hashlib.sha256(content).hexdigest()),
            *(
                Upload(manifest_path.parent / entry.filename, entry.sha256)
                for entry in manifest.artifacts
            ),
        )
    return ReleasePlan(
        forge=forge.name,
        tool=tool,
        repository=f"{urlsplit(forge.web).netloc}/{forge.repository}",
        tag=tag,
        revision=revision,
        title=tag,
        notes=notes,
        uploads=uploads,
    )


def execute(root: Path, prepared: ReleasePlan, *, dry_run: bool = False) -> str:
    """Create the release entry and return the URL the forge reports for it.

    A dry run narrates the command it would run and returns nothing, because
    no entry exists to point at.
    """
    if dry_run:
        reporting.command(
            _command(prepared, Path("<temporary release notes>"), prepared.assets),
            cwd=root,
            executed=False,
        )
        return ""
    try:
        with tempfile.TemporaryDirectory(prefix="releasing-notes-") as value:
            notes_file = Path(value) / "notes.md"
            notes_file.write_text(prepared.notes, encoding="utf-8", newline="")
            with stage(prepared.uploads) as assets:
                reported = processes.run(
                    _command(prepared, notes_file, assets),
                    cwd=root,
                    timeout=600,
                    echo=True,
                )
    except (OSError, UnicodeError) as exc:
        raise ForgeReleaseError(f"cannot stage the release notes: {exc}") from exc
    return reported.strip()


def _command(
    prepared: ReleasePlan, notes_file: Path, assets: tuple[Path, ...]
) -> list[str]:
    """The release invocation, shared by execution and its dry-run narration."""
    return [
        str(processes.executable(prepared.tool)),
        "release",
        "create",
        prepared.tag,
        "--verify-tag",
        "--title",
        prepared.title,
        "--repo",
        prepared.repository,
        "--notes-file",
        str(notes_file),
        *[str(path) for path in assets],
    ]


def _tag_revision(root: Path, tag: str) -> str:
    """Resolve only the release tag, never a branch with the same name."""
    try:
        return processes.git(
            root,
            "rev-parse",
            "--verify",
            "--end-of-options",
            f"refs/tags/{tag}^{{commit}}",
        ).strip()
    except processes.ProcessError as exc:
        raise ForgeReleaseError(f"cannot resolve release tag {tag}: {exc}") from exc


def _revision_text(root: Path, revision: str, path: str) -> str:
    try:
        return processes.git(root, "show", f"{revision}:{path}")
    except (processes.ProcessError, UnicodeError) as exc:
        raise ForgeReleaseError(f"cannot read {path} at {revision}: {exc}") from exc


def _notes(
    root: Path, config: ReleaseConfig, version_string: str, revision: str
) -> str:
    if config.changelog_format == "antsibull":
        changes = _revision_text(root, revision, antsibull.CHANGES.as_posix())
        config_path = antsibull.CONFIG.as_posix()
        listed = processes.git(
            root, "ls-tree", "--name-only", revision, "--", config_path
        )
        titles = _revision_text(root, revision, config_path) if listed.strip() else None
        try:
            return antsibull.notes_from_text(changes, version_string, config=titles)
        except antsibull.AntsibullError as exc:
            raise ForgeReleaseError(str(exc)) from exc
    text = _revision_text(root, revision, config.changelog)
    try:
        return changelog.show(text, version_string)
    except changelog.ChangelogError as exc:
        raise ForgeReleaseError(str(exc)) from exc
