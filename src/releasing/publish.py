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

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from releasing import artifacts, processes, reporting
from releasing.artifacts import Manifest

_INDEXES = frozenset({"pypi", "galaxy"})

# uv reads either a token or a password; both mean a credential is present.
_PYPI_VARIABLES = ("UV_PUBLISH_TOKEN", "UV_PUBLISH_PASSWORD")

# Galaxy has no single variable. ansible-core builds the name from the server's
# own name and only for a server that GALAXY_SERVER_LIST names, so a token set
# under any other name is read by nobody and the upload fails unauthenticated.
_GALAXY_LIST = "ANSIBLE_GALAXY_SERVER_LIST"
_GALAXY_TOKEN_PATH = "ANSIBLE_GALAXY_TOKEN_PATH"


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
    if index not in _INDEXES:
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


def credential_warning(
    index: str, environ: Mapping[str, str] | None = None
) -> tuple[str, tuple[str, ...]] | None:
    """Why the index's tool would find no credential, or None when it will.

    An upload can also be authorised by trusted publishing or by a
    configuration file, so a negative answer is a warning rather than a
    refusal. It exists because the alternative is a rejected upload after the
    tag is already pushed.
    """
    env = os.environ if environ is None else environ
    if index == "pypi":
        if any(env.get(name) for name in _PYPI_VARIABLES):
            return None
        return (
            f"{_PYPI_VARIABLES[0]} is unset; uv may use a configured credential",
            (),
        )
    if index == "galaxy":
        return _galaxy_warning(env)
    return None


def _galaxy_warning(env: Mapping[str, str]) -> tuple[str, tuple[str, ...]] | None:
    """The Galaxy credential a named server or a token file provides."""
    for name in (part.strip() for part in env.get(_GALAXY_LIST, "").split(",")):
        if not name:
            continue
        prefix = f"ANSIBLE_GALAXY_SERVER_{name.upper()}_"
        if env.get(f"{prefix}TOKEN"):
            return None
        if env.get(f"{prefix}USERNAME") and env.get(f"{prefix}PASSWORD"):
            return None
    if _galaxy_token_file(env) is not None:
        return None
    return (
        "no Galaxy credential found; ansible-galaxy names the variable after "
        "the server and reads it only for a server it was told about",
        (
            "export ANSIBLE_GALAXY_SERVER_LIST=galaxy",
            "export ANSIBLE_GALAXY_SERVER_GALAXY_URL=https://galaxy.ansible.com/api/",
            "export ANSIBLE_GALAXY_SERVER_GALAXY_TOKEN=...",
            f"or point {_GALAXY_TOKEN_PATH} at a file holding 'token: ...'",
        ),
    )


def _galaxy_token_file(env: Mapping[str, str]) -> Path | None:
    """The token file ansible-galaxy would read, when it holds anything.

    ansible-core creates the file empty on first use, so an empty one is the
    absence of a credential rather than one.
    """
    configured = env.get(_GALAXY_TOKEN_PATH)
    if configured:
        path = Path(configured)
    else:
        home = env.get("ANSIBLE_HOME")
        path = (Path(home) if home else Path.home() / ".ansible") / "galaxy_token"
    try:
        return path if path.is_file() and path.stat().st_size > 0 else None
    except OSError:
        return None
