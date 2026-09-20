# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later
"""Create the forge's release entry for a tag, through the forge's own tool.

The notes are the changelog section for that version and the assets are the
manifest's files, so the release entry cannot drift from what was written and
what was validated. The write itself is delegated to the forge's command-line
tool, which already owns an authenticated session. This package never holds a
credential that can write to a repository.
"""

from dataclasses import dataclass
from pathlib import Path

from releasing import artifacts, changelog, forge_api, processes
from releasing.artifacts import Manifest
from releasing.config import ReleaseConfig
from releasing.forges import Forge

_TOOLS = {"github": "gh"}


class ForgeReleaseError(RuntimeError):
    """The release entry cannot be created as asked."""


@dataclass(frozen=True)
class ReleasePlan:
    """What the forge entry would say and carry."""

    forge: str
    tool: str
    tag: str
    title: str
    notes: str
    assets: tuple[Path, ...]


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
    """Assemble the entry from the changelog and the manifest, and check it can be made."""
    try:
        tool = _TOOLS[forge.name]
    except KeyError as exc:
        raise ForgeReleaseError(
            f"no release tool is known for the {forge.name} forge"
        ) from exc
    processes.executable(tool)
    tag = config.tag(version_string)
    if not offline and forge_api.release_exists(forge, tag):
        raise ForgeReleaseError(
            f"{forge.name} already has a release for {tag}; a release entry is "
            "created once and the version is spent"
        )
    notes = _notes(root, config, version_string)
    assets: tuple[Path, ...] = ()
    if manifest is not None and manifest_path is not None:
        problems = artifacts.verify_manifest(manifest, manifest_path.parent)
        if problems:
            raise ForgeReleaseError(
                "the files beside the manifest are not the validated set:\n  "
                + "\n  ".join(problems)
            )
        assets = (
            manifest_path,
            *(manifest_path.parent / entry.filename for entry in manifest.artifacts),
        )
    return ReleasePlan(
        forge=forge.name,
        tool=tool,
        tag=tag,
        title=tag,
        notes=notes,
        assets=assets,
    )


def execute(root: Path, prepared: ReleasePlan, *, dry_run: bool = False) -> list[str]:
    """Create the release entry. Return the command that was run, or would be."""
    notes_file = root / f".releasing-notes-{prepared.tag}"
    argv = [
        str(processes.executable(prepared.tool)),
        "release",
        "create",
        prepared.tag,
        "--title",
        prepared.title,
        "--notes-file",
        str(notes_file),
        *[str(path) for path in prepared.assets],
    ]
    if dry_run:
        return argv
    try:
        notes_file.write_text(prepared.notes, encoding="utf-8")
        processes.run(argv, cwd=root, timeout=600)
    except (OSError, UnicodeError) as exc:
        raise ForgeReleaseError(f"cannot stage the release notes: {exc}") from exc
    finally:
        notes_file.unlink(missing_ok=True)
    return argv


def _notes(root: Path, config: ReleaseConfig, version_string: str) -> str:
    if config.changelog_format == "antsibull":
        raise ForgeReleaseError(
            "antsibull-changelog owns this changelog; supply --notes-file yourself"
        )
    path = root / config.changelog
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ForgeReleaseError(f"cannot read {config.changelog}: {exc}") from exc
    try:
        return changelog.show(text, version_string)
    except changelog.ChangelogError as exc:
        raise ForgeReleaseError(str(exc)) from exc
