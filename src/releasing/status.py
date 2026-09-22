# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later
"""Where a release stands: which of its steps are done, pending or broken.

A release spans several commands and often several sittings. This reports what
is true of one version right now, so nobody has to reconstruct it from a
handful of Git and index queries. It performs no step and writes nothing.

Each fact is one of four states. ``ok`` is done. ``pending`` is not done yet
and nothing is wrong. ``problem`` is done wrongly and needs attention rather
than continuation. ``unknown`` is a service that could not be reached, which
is neither progress nor breakage.
"""

from dataclasses import dataclass
from pathlib import Path

from releasing import changelog, forge_api, processes, verify
from releasing import tag as tagging
from releasing.artifacts import Manifest
from releasing.config import ReleaseConfig
from releasing.forges import Forge

# A report is run interactively; an unreachable remote should not hold it for
# the full bound that a correctness-critical command accepts.
REMOTE_QUERY_TIMEOUT = 20.0

OK = "ok"
PENDING = "pending"
PROBLEM = "problem"
UNKNOWN = "unknown"


@dataclass(frozen=True)
class Step:
    """One fact about a release and what it means."""

    name: str
    state: str
    detail: str


@dataclass(frozen=True)
class Status:
    """Every fact gathered about one version."""

    version: str
    tag: str
    steps: tuple[Step, ...]

    @property
    def complete(self) -> bool:
        """Whether every fact is done and none is broken or unreachable."""
        return all(step.state == OK for step in self.steps)

    @property
    def broken(self) -> tuple[Step, ...]:
        """The facts that need attention rather than continuation."""
        return tuple(step for step in self.steps if step.state == PROBLEM)


def collect(
    root: Path,
    config: ReleaseConfig,
    forge: Forge,
    version_string: str,
    *,
    manifest: Manifest | None = None,
    remote: str = processes.DEFAULT_REMOTE,
    offline: bool = False,
) -> Status:
    """Gather what is true of ``version_string`` locally, on the index and the forge."""
    tag = config.tag(version_string)
    steps = [_changelog_step(root, config, forge, version_string)]
    # Local facts first, then the remote one separately: a report degrades to
    # "unknown" where a service is unreachable instead of failing outright.
    tag_state = tagging.state(root, forge, tag, offline=True, remote=None)
    remote_revision: str | None = None
    remote_state: str | None = None
    if not offline:
        try:
            listing = processes.git(
                root,
                "ls-remote",
                "--tags",
                remote,
                f"refs/tags/{tag}",
                remote=True,
                timeout=REMOTE_QUERY_TIMEOUT,
            )
        except processes.ProcessError as exc:
            remote_state = str(exc)
        else:
            remote_revision = (
                listing.split("\t")[0].strip() if listing.strip() else None
            )
    steps.extend(
        _tag_steps(
            root,
            config,
            tag,
            tag_state,
            version_string,
            manifest,
            remote=remote,
            remote_revision=remote_revision,
            remote_unreachable=remote_state,
            offline=offline,
        )
    )
    if offline:
        steps.append(Step("index", UNKNOWN, "not queried"))
        steps.append(Step("forge release", UNKNOWN, "not queried"))
        return Status(version_string, tag, tuple(steps))
    steps.append(_index_step(config, version_string, manifest))
    steps.append(_forge_step(forge, tag))
    return Status(version_string, tag, tuple(steps))


def _changelog_step(
    root: Path, config: ReleaseConfig, forge: Forge, version_string: str
) -> Step:
    if config.changelog_format == "antsibull":
        path = root / "changelogs" / "changelog.yaml"
        name = "changelogs/changelog.yaml"
    else:
        path = root / config.changelog
        name = config.changelog
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return Step("changelog", PROBLEM, f"cannot read {name}: {exc}")
    if config.changelog_format == "antsibull":
        if changelog.antsibull_has_release(text, version_string):
            return Step("changelog", OK, f"{name} records {version_string}")
        return Step("changelog", PENDING, f"{name} has no release {version_string}")
    problems = changelog.check(
        text, forge=forge, tag_format=config.tag_format, version=version_string
    )
    if not problems:
        return Step("changelog", OK, f"{name} documents {version_string}")
    try:
        changelog.show(text, version_string)
    except changelog.ChangelogError:
        return Step("changelog", PENDING, f"{name} has no section for {version_string}")
    return Step("changelog", PROBLEM, "; ".join(problems))


def _tag_steps(
    root: Path,
    config: ReleaseConfig,
    tag: str,
    tag_state: tagging.TagState,
    version_string: str,
    manifest: Manifest | None,
    *,
    remote: str = processes.DEFAULT_REMOTE,
    remote_revision: str | None = None,
    remote_unreachable: str | None = None,
    offline: bool = False,
) -> list[Step]:
    steps: list[Step] = []
    if tag_state.revision is None:
        steps.append(Step("tag", PENDING, f"{tag} does not exist locally"))
    else:
        expected = config.tag_message_for(version_string)
        if not tag_state.annotated:
            steps.append(Step("tag", PROBLEM, f"{tag} is lightweight"))
        elif tag_state.message != expected:
            steps.append(Step("tag", PROBLEM, f"{tag} says {tag_state.message!r}"))
        else:
            steps.append(Step("tag", OK, f"{tag} at {tag_state.revision[:12]}"))
    if offline:
        steps.append(Step("tag pushed", UNKNOWN, "not queried"))
    elif remote_unreachable is not None:
        steps.append(Step("tag pushed", UNKNOWN, remote_unreachable))
    elif remote_revision is None:
        steps.append(Step("tag pushed", PENDING, f"{tag} is not on {remote}"))
    elif tag_state.revision is None:
        steps.append(Step("tag pushed", PROBLEM, f"{tag} is on {remote} but not local"))
    else:
        local_object = processes.git(root, "rev-parse", f"refs/tags/{tag}").strip()
        if remote_revision == local_object:
            steps.append(Step("tag pushed", OK, f"{remote} matches this repository"))
        else:
            steps.append(
                Step("tag pushed", PROBLEM, f"{tag} differs between {remote} and local")
            )
    if manifest is not None and manifest.source_revision is not None:
        if tag_state.revision is None:
            steps.append(
                Step("artifact revision", PENDING, "no tag to compare the manifest to")
            )
        elif manifest.source_revision == tag_state.revision:
            steps.append(
                Step("artifact revision", OK, "artifacts were built from the tag")
            )
        else:
            steps.append(
                Step(
                    "artifact revision",
                    PROBLEM,
                    f"artifacts were built from {manifest.source_revision[:12]}, "
                    f"tag names {tag_state.revision[:12]}",
                )
            )
    return steps


def _index_step(
    config: ReleaseConfig, version_string: str, manifest: Manifest | None
) -> Step:
    if config.index == "none":
        return Step("index", OK, "this ecosystem publishes nothing")
    name = None
    if manifest is not None:
        try:
            name, manifest = verify.select_distribution(
                manifest, index=config.index, version=version_string
            )
        except verify.VerificationError as exc:
            return Step("index", PROBLEM, str(exc))
    if name is None:
        return Step("index", UNKNOWN, "pass --manifest to identify the distribution")
    try:
        published = verify.index_files(config.index, name, version_string)
    except verify.VerificationError as exc:
        if "not published" in str(exc):
            return Step(
                "index", PENDING, f"{config.index} has no {name} {version_string}"
            )
        return Step("index", UNKNOWN, str(exc))
    problems = verify.compare_with_manifest(manifest, published) if manifest else []
    if problems:
        return Step("index", PROBLEM, "; ".join(problems))
    return Step("index", OK, f"{config.index} serves the validated files")


def _forge_step(forge: Forge, tag: str) -> Step:
    try:
        exists = forge_api.release_exists(forge, tag)
    except forge_api.ForgeError as exc:
        return Step("forge release", UNKNOWN, str(exc))
    if exists:
        return Step("forge release", OK, f"{forge.name} has a release for {tag}")
    return Step("forge release", PENDING, f"{forge.name} has no release for {tag}")
