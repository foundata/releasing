# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later
"""Publish a release's branch and tag together, in that order.

Two pushes, one step. A tag pushed without its branch names a commit the
remote does not have on any branch, which is how a release comes to exist on
the forge that nobody can check out. Doing both here also allows the checks a
bare ``git push`` cannot make: that the tag is the project's release tag for
the version, that the revision it names states that version, and that the
branch being pushed actually contains it.
"""

from dataclasses import dataclass
from pathlib import Path

from releasing import processes, reporting
from releasing import tag as tagging
from releasing.config import ReleaseConfig
from releasing.forges import Forge

DEFAULT_REMOTE = processes.DEFAULT_REMOTE


class PushError(RuntimeError):
    """The branch and tag cannot be published safely."""


@dataclass(frozen=True)
class PushPlan:
    """What publishing this release would send, and where."""

    remote: str
    branch: str
    tag: str
    revision: str
    version: str


def plan(
    root: Path,
    config: ReleaseConfig,
    forge: Forge,
    version_string: str,
    *,
    remote: str = DEFAULT_REMOTE,
) -> PushPlan:
    """Check that the branch and tag can be published, and describe what would be."""
    tag = config.tag(version_string)
    branch = processes.git(root, "rev-parse", "--abbrev-ref", "HEAD").strip()
    if branch == "HEAD":
        raise PushError("HEAD is detached; check out the release branch first")
    revision = _tag_commit(root, tag)
    problems = tagging.check(
        root,
        config,
        forge,
        version_string,
        revision=revision,
        offline=True,
        remote=remote,
    )
    if problems:
        raise PushError(f"{tag} is not usable:\n  " + "\n  ".join(problems))
    if not _contains(root, branch, revision):
        raise PushError(
            f"{branch} does not contain {tag} ({revision[:12]}); pushing the tag "
            "would publish a commit that is on no branch"
        )
    reporting.phase(f"Verified {branch} contains {tag} ({revision[:12]})")
    found = tagging.check_revision(root, revision, version_string)
    return PushPlan(
        remote=remote, branch=branch, tag=tag, revision=revision, version=found
    )


def execute(root: Path, prepared: PushPlan, *, dry_run: bool = False) -> list[str]:
    """Push the branch, then the tag. Return what was sent."""
    options = ["--dry-run"] if dry_run else []
    sent = []
    # The branch first: until it lands, the tag would name an unreachable commit.
    processes.git(
        root, "push", *options, prepared.remote, prepared.branch, remote=True, echo=True
    )
    sent.append(prepared.branch)
    processes.git(
        root,
        "push",
        *options,
        prepared.remote,
        f"refs/tags/{prepared.tag}",
        remote=True,
        echo=True,
    )
    sent.append(prepared.tag)
    return sent


def _tag_commit(root: Path, tag: str) -> str:
    listed = processes.git(root, "tag", "--list", tag).strip()
    if not listed:
        raise PushError(f"tag {tag} does not exist; create it before pushing")
    return processes.git(root, "rev-parse", f"{tag}^{{commit}}").strip()


def _contains(root: Path, branch: str, revision: str) -> bool:
    try:
        processes.git(root, "merge-base", "--is-ancestor", revision, branch)
    except processes.ProcessError:
        return False
    return True
