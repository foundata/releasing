# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later
"""Release tags: create one under guard, or delete one while that is still legal.

A release tag is annotated, carries the project's message convention and points
at the revision whose artifacts were built. Deleting a tag is legal only while
no forge release exists for it, which is exactly what the documented "delete
the tag and start over" escape depends on; once a release exists the version is
spent and the fix needs a new one.
"""

import tempfile
from dataclasses import dataclass
from pathlib import Path

from releasing import build, changelog, forge_api, processes, version
from releasing.config import ReleaseConfig, load_release_config
from releasing.forges import Forge, forge_for


class TagError(RuntimeError):
    """A tag cannot be created or deleted safely."""


@dataclass(frozen=True)
class TagState:
    """What the local repository and the forge say about one tag."""

    tag: str
    revision: str | None
    annotated: bool
    message: str
    remote_revision: str | None
    release_exists: bool


def state(
    root: Path, config: ReleaseConfig, forge: Forge, tag: str, *, offline: bool = False
) -> TagState:
    """Collect the local and remote facts about ``tag``."""
    listed = processes.git(root, "tag", "--list", tag).strip()
    revision = annotated_message = None
    annotated = False
    if listed:
        kind = processes.git(root, "cat-file", "-t", tag).strip()
        annotated = kind == "tag"
        revision = processes.git(root, "rev-parse", f"{tag}^{{commit}}").strip()
        annotated_message = (
            processes.git(
                root, "tag", "--list", "--format=%(contents:subject)", tag
            ).strip()
            if annotated
            else ""
        )
    remote = processes.git(root, "ls-remote", "--tags", "origin", f"refs/tags/{tag}")
    remote_revision = remote.split("\t")[0].strip() if remote.strip() else None
    return TagState(
        tag=tag,
        revision=revision,
        annotated=annotated,
        message=annotated_message or "",
        remote_revision=remote_revision,
        release_exists=(False if offline else forge_api.release_exists(forge, tag)),
    )


def create(
    root: Path,
    config: ReleaseConfig,
    forge: Forge,
    version_string: str,
    *,
    revision: str = "HEAD",
    offline: bool = False,
) -> str:
    """Create the annotated release tag for ``version_string`` under guard.

    The working tree must be clean. The selected revision's declaration,
    version sites, lockfile, pins and changelog must agree with the version,
    and the tag must exist neither locally nor on the remote.
    """
    tag = config.tag(version_string)
    status = processes.git(root, "status", "--porcelain", "--untracked-files=all")
    if status.strip():
        raise TagError(
            "the working tree is not clean; a tag must name a committed state:\n"
            + status.rstrip()
        )
    target = processes.git(
        root, "rev-parse", "--verify", f"{revision}^{{commit}}"
    ).strip()
    found = _check_revision(root, target, version_string)
    current = state(root, config, forge, tag, offline=offline)
    if current.revision is not None:
        raise TagError(f"tag {tag} already exists locally at {current.revision[:12]}")
    if current.remote_revision is not None:
        raise TagError(f"tag {tag} already exists on the remote")
    processes.git(root, "tag", "-a", tag, target, "-m", config.tag_message_for(found))
    return tag


def _check_revision(root: Path, revision: str, expected: str) -> str:
    with tempfile.TemporaryDirectory(prefix="releasing-tag-") as value:
        exported = Path(value)
        build.export(root, revision, exported)
        config = load_release_config(exported)
        found = version.check(exported, config, expect=expected)
        path = exported / (
            "changelogs/changelog.yaml"
            if config.changelog_format == "antsibull"
            else config.changelog
        )
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise TagError(f"cannot read {path.relative_to(exported)}: {exc}") from exc
        if config.changelog_format == "antsibull":
            if not changelog.antsibull_has_release(text, found):
                raise TagError(f"changelogs/changelog.yaml has no release {found}")
        else:
            problems = changelog.check(
                text,
                forge=forge_for(config),
                tag_format=config.tag_format,
                version=found,
            )
            if problems:
                raise TagError(f"{config.changelog}:\n" + "\n".join(problems))
        return found


def delete(
    root: Path,
    config: ReleaseConfig,
    forge: Forge,
    version_string: str,
    *,
    remote: bool = True,
    offline: bool = False,
) -> list[str]:
    """Delete the release tag locally and on the remote while no release exists."""
    tag = config.tag(version_string)
    current = state(root, config, forge, tag, offline=offline)
    if current.release_exists:
        raise TagError(
            f"a {forge.name} release exists for {tag}; the version is spent. "
            "Publish the fix as a new version instead of moving this tag."
        )
    if current.revision is None and current.remote_revision is None:
        raise TagError(f"tag {tag} exists neither locally nor on the remote")
    deleted = []
    if current.revision is not None:
        processes.git(root, "tag", "-d", tag)
        deleted.append("local")
    if remote and current.remote_revision is not None:
        processes.git(root, "push", "origin", f":refs/tags/{tag}")
        deleted.append("remote")
    return deleted


def check(
    root: Path,
    config: ReleaseConfig,
    forge: Forge,
    version_string: str,
    *,
    revision: str = "HEAD",
    offline: bool = False,
) -> list[str]:
    """Return every reason the tag is not a valid release tag for the version."""
    tag = config.tag(version_string)
    target = processes.git(
        root, "rev-parse", "--verify", f"{revision}^{{commit}}"
    ).strip()
    current = state(root, config, forge, tag, offline=offline)
    problems = []
    if current.revision is None:
        return [f"tag {tag} does not exist"]
    if not current.annotated:
        problems.append(f"tag {tag} is lightweight; release tags are annotated")
    expected = config.tag_message_for(version_string)
    if current.annotated and current.message != expected:
        problems.append(f"tag {tag} says {current.message!r}, expected {expected!r}")
    if current.revision != target:
        problems.append(
            f"tag {tag} points at {current.revision[:12]}, not {target[:12]}"
        )
    if (
        current.remote_revision is not None
        and current.remote_revision != current.revision
    ):
        problems.append(f"tag {tag} differs between the remote and this repository")
    return problems
