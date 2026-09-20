# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later
"""Post-publish verification: the index serves what was validated.

Three questions after an upload. Does the index serve, for this version, files
whose digests match the manifest the build recorded? Does an isolated install
of that version report it? Does the forge report the version's tag as the
latest release? A release that cannot answer all three is not finished.
"""

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, replace
from pathlib import Path

from releasing import forge_api, processes
from releasing.artifacts import Manifest, ManifestEntry
from releasing.forges import Forge

TIMEOUT = 30.0
_USER_AGENT = "foundata-releasing"


class VerificationError(RuntimeError):
    """The published release could not be verified."""


@dataclass(frozen=True)
class IndexFile:
    """One file the index serves for a version."""

    filename: str
    sha256: str


def pypi_files(name: str, version: str) -> list[IndexFile]:
    """The files PyPI serves for one version of one distribution."""
    url = f"https://pypi.org/pypi/{name}/{version}/json"
    document = _get(url)
    urls = document.get("urls") if isinstance(document, dict) else None
    if not isinstance(urls, list) or not urls:
        raise VerificationError(f"{url}: no files published for {name} {version}")
    files = []
    for entry in urls:
        digests = entry.get("digests", {}) if isinstance(entry, dict) else {}
        digest = digests.get("sha256") if isinstance(digests, dict) else None
        filename = entry.get("filename") if isinstance(entry, dict) else None
        if not isinstance(filename, str) or not isinstance(digest, str):
            raise VerificationError(f"{url}: a published file lacks name or digest")
        files.append(IndexFile(filename, digest))
    return files


def galaxy_files(name: str, version: str) -> list[IndexFile]:
    """The artifact Ansible Galaxy serves for one version of one collection."""
    namespace, _, collection = name.partition(".")
    if not namespace or not collection:
        raise VerificationError(f"not a collection name: {name!r}")
    url = (
        "https://galaxy.ansible.com/api/v3/plugin/ansible/content/published/"
        f"collections/index/{namespace}/{collection}/versions/{version}/"
    )
    document = _get(url)
    artifact = document.get("artifact") if isinstance(document, dict) else None
    if not isinstance(artifact, dict):
        raise VerificationError(f"{url}: the published version has no artifact")
    filename, digest = artifact.get("filename"), artifact.get("sha256")
    if not isinstance(filename, str) or not isinstance(digest, str):
        raise VerificationError(f"{url}: the artifact lacks a name or digest")
    return [IndexFile(filename, digest)]


def index_files(index: str, name: str, version: str) -> list[IndexFile]:
    """The files the declared index serves for one version."""
    if index == "pypi":
        return pypi_files(name, version)
    if index == "galaxy":
        return galaxy_files(name, version)
    raise VerificationError(f"the {index} index publishes nothing to verify")


def select_distribution(
    manifest: Manifest, *, index: str, version: str, distribution: str | None = None
) -> tuple[str, Manifest]:
    """Select one distribution's entries without changing the manifest schema.

    Infer the name only for a single distribution. Python names compare with
    case, hyphens, underscores and dots normalized; Galaxy names retain their
    namespace and collection spelling. No local artifact files are required.
    """
    if index not in {"pypi", "galaxy"}:
        raise VerificationError(f"the {index} index publishes nothing to verify")
    if not version:
        raise VerificationError("the manifest has no version; pass --version")
    grouped: dict[str, list[ManifestEntry]] = {}
    for entry in manifest.artifacts:
        name = _distribution_name(entry.filename, index, version)
        grouped.setdefault(name, []).append(entry)
    if distribution is None:
        if len(grouped) != 1:
            raise VerificationError(
                "cannot tell which distribution to verify; pass --distribution"
            )
        distribution = next(iter(grouped))
    elif index == "pypi":
        distribution = re.sub(r"[-_.]+", "-", distribution).lower()
    if distribution not in grouped:
        raise VerificationError(f"no artifacts for {distribution} in the manifest")
    return distribution, replace(manifest, artifacts=tuple(grouped[distribution]))


def _distribution_name(filename: str, index: str, version: str) -> str:
    suffix = f"-{version}.tar.gz"
    if index == "pypi" and filename.endswith(".whl") and "-" in filename:
        name = filename.partition("-")[0]
    elif filename.endswith(suffix):
        name = filename.removesuffix(suffix)
        if index == "galaxy":
            namespace, separator, collection = name.partition("-")
            if not separator or not namespace or not collection:
                raise VerificationError(f"cannot identify collection from {filename!r}")
            return f"{namespace}.{collection}"
    else:
        raise VerificationError(f"cannot identify distribution from {filename!r}")
    return re.sub(r"[-_.]+", "-", name).lower()


def compare_with_manifest(manifest: Manifest, published: list[IndexFile]) -> list[str]:
    """Return every manifest file the index does not serve with the same digest."""
    served = {entry.filename: entry.sha256 for entry in published}
    problems = []
    for entry in manifest.artifacts:
        if entry.filename not in served:
            problems.append(f"{entry.filename}: not published")
        elif served[entry.filename] != entry.sha256:
            problems.append(
                f"{entry.filename}: published digest differs from the validated file"
            )
    for filename in sorted(
        set(served) - {entry.filename for entry in manifest.artifacts}
    ):
        problems.append(f"{filename}: published but not in the manifest")
    return problems


def installed_version(name: str, version: str, command: str | None = None) -> str:
    """Install the published version in an isolated environment and ask its version.

    The package's index metadata is refreshed rather than taken from the local
    cache. This check runs moments after an upload, which is exactly when a
    cached index listing still predates the version being verified and would
    report it as nonexistent.
    """
    uv = str(processes.executable("uv"))
    invocation = [
        uv,
        "run",
        "--isolated",
        "--no-project",
        "--refresh-package",
        name,
        "--with",
        f"{name}=={version}",
        "--",
    ]
    if command is None:
        script = f"from importlib.metadata import version; print(version({name!r}))"
        invocation += ["python", "-c", script]
    else:
        invocation += [command, "--version"]
    return processes.run(invocation, timeout=900).strip()


def latest_tag(forge: Forge) -> str | None:
    """The tag the forge reports as its latest release."""
    return forge_api.latest_release_tag(forge)


def _get(url: str) -> object:
    request = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": _USER_AGENT}
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # The error carries an open response body; release it either way.
        exc.close()
        if exc.code == 404:
            raise VerificationError(f"{url}: not published (HTTP 404)") from exc
        raise VerificationError(f"{url}: HTTP {exc.code} {exc.reason}") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise VerificationError(f"{url}: {exc}") from exc


def manifest_path_for(directory: Path) -> Path:
    """The manifest inside a build output directory."""
    return directory / "artifacts.json"
