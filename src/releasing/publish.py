# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later
"""Upload exactly the files a manifest names, and nothing else.

``uv publish dist/*`` trusts a glob, and a glob picks up whatever the last
build left behind. Taking the manifest instead makes the upload set the
validated set by construction: every file is named, its digest is re-checked
against the bytes on disk, and a file beside them that nobody validated is a
refusal rather than an extra upload.

Credentials never pass through here. The index tool reads them from the
environment, from trusted publishing, or from its own configuration.
"""

from dataclasses import dataclass
from pathlib import Path

from releasing import artifacts, processes, reporting
from releasing.artifacts import Manifest

_TOKEN_VARIABLES = {
    "pypi": "UV_PUBLISH_TOKEN",
    "galaxy": "ANSIBLE_GALAXY_SERVER_TOKEN",
}


class PublishError(RuntimeError):
    """The manifest's files cannot be published as they stand."""


@dataclass(frozen=True)
class PublishPlan:
    """The exact files an upload would send."""

    index: str
    version: str
    files: tuple[Path, ...]


def plan(manifest: Manifest, directory: Path, *, index: str) -> PublishPlan:
    """Re-verify the manifest against the directory and list what to upload."""
    if index not in _TOKEN_VARIABLES:
        raise PublishError(f"the {index} index publishes nothing")
    reporting.phase(
        f"Re-checking {len(manifest.artifacts)} file(s) against the manifest"
    )
    problems = artifacts.verify_manifest(manifest, directory)
    if problems:
        raise PublishError(
            "the files beside the manifest are not the validated set:\n  "
            + "\n  ".join(problems)
        )
    files = tuple(directory / entry.filename for entry in manifest.artifacts)
    return PublishPlan(index=index, version=manifest.version, files=files)


def execute(prepared: PublishPlan, *, dry_run: bool = False) -> list[str]:
    """Upload the planned files through the index's own tool."""
    if dry_run:
        return [path.name for path in prepared.files]
    if prepared.index == "pypi":
        uv = str(processes.executable("uv"))
        processes.run(
            [uv, "publish", *[str(path) for path in prepared.files]],
            timeout=1800,
            stream=True,
            echo=True,
        )
    else:
        galaxy = str(processes.executable("ansible-galaxy"))
        for path in prepared.files:
            processes.run(
                [galaxy, "collection", "publish", str(path)],
                timeout=1800,
                stream=True,
                echo=True,
            )
    return [path.name for path in prepared.files]


def token_variable(index: str) -> str:
    """The environment variable the index's tool reads its credential from."""
    try:
        return _TOKEN_VARIABLES[index]
    except KeyError as exc:
        raise PublishError(f"the {index} index publishes nothing") from exc
