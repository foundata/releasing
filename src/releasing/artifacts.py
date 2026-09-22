# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later
"""Distribution artifacts: inspect them, check them, record their digests.

Wheels, source distributions and Ansible collection tarballs are inspected
without extraction. The checks are the ones that caught real defects: the
version in the metadata and in the file name, relative links in the
description that break on the index, tool caches and bytecode that leaked into
a published wheel, and unsafe archive members. The manifest records the
SHA-256 of every file that passed, so what is uploaded and later served can be
compared with what was validated. Nothing here runs Git or another program.
"""

import hashlib
import json
import re
import stat
import tarfile
import zipfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from releasing import markdown

SCHEMA_VERSION = 1
MANIFEST = "artifacts.json"
_FORBIDDEN_PARTS = frozenset(
    {
        ".git",
        ".hypothesis",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
    }
)
_FORBIDDEN_NAMES = frozenset({".coverage", ".DS_Store"})
_FORBIDDEN_SUFFIXES = frozenset({".pyc", ".pyo", ".orig", ".rej"})
# uv_build keeps the untransformed project file beside the rewritten one in
# every source distribution, so this one name is expected rather than litter.
_EXPECTED_NAMES = frozenset({"pyproject.toml.orig"})


class ArtifactError(ValueError):
    """An artifact cannot be read or is not a supported distribution."""


@dataclass(frozen=True)
class Artifact:
    """What an archive says about itself: kind, name, version, description, members."""

    path: Path
    kind: str
    name: str
    version: str
    description: str
    members: tuple[str, ...]


def inspect(path: Path) -> Artifact:
    """Read the metadata and member list of a wheel, sdist or collection tarball."""
    if path.suffix == ".whl":
        return _inspect_wheel(path)
    if path.name.endswith(".tar.gz"):
        return _inspect_tarball(path)
    raise ArtifactError(f"{path.name}: not a wheel, sdist or collection tarball")


def check(
    artifacts: Iterable[Artifact], *, version: str, names: Sequence[str] = ()
) -> list[str]:
    """Return every problem that makes the artifacts unpublishable.

    ``version`` is the version every artifact must carry in its metadata and
    file name. ``names`` are the distribution names that must all be present.
    """
    problems: list[str] = []
    seen: set[str] = set()
    for artifact in artifacts:
        where = artifact.path.name
        seen.add(artifact.name)
        if artifact.version != version:
            problems.append(
                f"{where}: metadata version {artifact.version} != {version}"
            )
        if version not in artifact.path.name:
            problems.append(f"{where}: file name does not carry version {version}")
        for member in artifact.members:
            problems.extend(f"{where}: {reason}" for reason in _member_problems(member))
        if artifact.kind != "wheel" or artifact.description:
            problems.extend(
                f"{where}: {reason}" for reason in _description_problems(artifact)
            )
    for name in names:
        if name not in seen:
            problems.append(
                f"no artifact for {name} among {', '.join(sorted(seen)) or 'none'}"
            )
    return problems


@dataclass(frozen=True)
class ManifestEntry:
    """One validated file and its digest."""

    filename: str
    sha256: str
    size: int


@dataclass(frozen=True)
class Manifest:
    """The validated set of files for one version of one repository."""

    repository: str
    version: str
    source_revision: str | None
    artifacts: tuple[ManifestEntry, ...]
    created: str


def sha256_file(path: Path) -> str:
    """Hex SHA-256 of a file's content."""
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ArtifactError(f"cannot read {path}: {exc}") from exc
    return digest.hexdigest()


def build_manifest(
    files: Sequence[Path], *, repository: str, version: str, source_revision: str | None
) -> Manifest:
    """Digest every file into a manifest; file names must be unique."""
    names = [path.name for path in files]
    if len(set(names)) != len(names):
        raise ArtifactError("artifact file names must be unique")
    if not files:
        raise ArtifactError("a manifest needs at least one artifact")
    return Manifest(
        repository=repository,
        version=version,
        source_revision=source_revision,
        artifacts=tuple(
            ManifestEntry(path.name, sha256_file(path), path.stat().st_size)
            for path in files
        ),
        created=datetime.now(UTC).isoformat(timespec="seconds"),
    )


_RESERVED_KEYS = frozenset(
    {
        "schemaVersion",
        "generator",
        "repository",
        "version",
        "sourceRevision",
        "created",
        "artifacts",
    }
)


def dump_manifest(
    manifest: Manifest, *, extra: Mapping[str, object] | None = None
) -> str:
    """The manifest as stable, indented JSON.

    ``extra`` adds producer-specific top-level keys, such as the revision of a
    guide a gate implements. They may not shadow the standard keys and must
    be JSON-serializable. Readers of the standard shape ignore them.
    """
    document: dict[str, object] = {
        "schemaVersion": SCHEMA_VERSION,
        "generator": "releasing",
        "repository": manifest.repository,
        "version": manifest.version,
        "sourceRevision": manifest.source_revision,
        "created": manifest.created,
    }
    for key, value in (extra or {}).items():
        if key in _RESERVED_KEYS:
            raise ArtifactError(f"extra manifest key {key!r} shadows a standard key")
        if not key or not isinstance(key, str):
            raise ArtifactError("extra manifest keys must be non-empty strings")
        document[key] = value
    document["artifacts"] = [
        {"filename": entry.filename, "sha256": entry.sha256, "size": entry.size}
        for entry in manifest.artifacts
    ]
    try:
        return json.dumps(document, indent=2) + "\n"
    except (TypeError, ValueError) as exc:
        raise ArtifactError(
            f"extra manifest keys must be JSON-serializable: {exc}"
        ) from exc


def load_manifest(path: Path) -> Manifest:
    """Read a manifest written by ``dump_manifest`` or a compatible one.

    Only the ``artifacts`` list with ``filename`` and ``sha256`` is required,
    so a manifest written by another gate in the same shape is accepted.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ArtifactError(f"cannot read manifest {path}: {exc}") from exc
    entries = data.get("artifacts") if isinstance(data, dict) else None
    if not isinstance(entries, list) or not entries:
        raise ArtifactError(f"{path}: manifest needs a non-empty artifacts list")
    artifacts = []
    for entry in entries:
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("filename"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", str(entry.get("sha256", "")))
        ):
            raise ArtifactError(f"{path}: every artifact needs filename and sha256")
        size = entry.get("size", -1)
        artifacts.append(
            ManifestEntry(
                str(entry["filename"]),
                str(entry["sha256"]),
                int(size) if isinstance(size, int) else -1,
            )
        )
    return Manifest(
        repository=str(data.get("repository", "")),
        version=str(data.get("version", "")),
        source_revision=(
            str(data["sourceRevision"])
            if isinstance(data.get("sourceRevision"), str)
            else None
        ),
        artifacts=tuple(artifacts),
        created=str(data.get("created", "")),
    )


def verify_manifest(manifest: Manifest, directory: Path) -> list[str]:
    """Return every file in ``directory`` that is missing, altered or unlisted."""
    problems: list[str] = []
    listed = {entry.filename for entry in manifest.artifacts}
    for entry in manifest.artifacts:
        path = directory / entry.filename
        if not path.is_file():
            problems.append(f"{entry.filename}: missing")
        elif sha256_file(path) != entry.sha256:
            problems.append(f"{entry.filename}: SHA-256 differs from the manifest")
    for path in sorted(directory.iterdir()):
        if (
            path.name not in listed
            and path.name != MANIFEST
            and (path.suffix == ".whl" or path.name.endswith(".tar.gz"))
        ):
            problems.append(f"{path.name}: not in the manifest")
    return problems


def _inspect_wheel(path: Path) -> Artifact:
    try:
        with zipfile.ZipFile(path) as archive:
            members = []
            for info in archive.infolist():
                if stat.S_ISLNK(info.external_attr >> 16):
                    raise ArtifactError(f"{path.name}: symbolic link {info.filename}")
                members.append(info.filename)
            metadata = [
                name for name in members if name.endswith(".dist-info/METADATA")
            ]
            if len(metadata) != 1:
                raise ArtifactError(
                    f"{path.name}: expected one METADATA, found {len(metadata)}"
                )
            text = archive.read(metadata[0]).decode("utf-8", errors="replace")
    except (OSError, zipfile.BadZipFile) as exc:
        raise ArtifactError(f"cannot read wheel {path}: {exc}") from exc
    name, version, description = _parse_metadata(text, path)
    return Artifact(path, "wheel", name, version, description, tuple(members))


def _inspect_tarball(path: Path) -> Artifact:
    try:
        with tarfile.open(path, mode="r:gz") as archive:
            members = []
            for member in archive.getmembers():
                if (
                    member.issym()
                    or member.islnk()
                    or not (member.isfile() or member.isdir())
                ):
                    raise ArtifactError(f"{path.name}: unsafe member {member.name}")
                members.append(member.name)
            manifest = [name for name in members if name == "MANIFEST.json"]
            if manifest:
                return _collection(path, archive, tuple(members))
            info = [
                name
                for name in members
                if name.count("/") == 1 and name.endswith("/PKG-INFO")
            ]
            if len(info) != 1:
                raise ArtifactError(
                    f"{path.name}: expected one PKG-INFO, found {len(info)}"
                )
            text = _extract(archive, info[0], path).decode("utf-8", errors="replace")
    except (OSError, tarfile.TarError) as exc:
        raise ArtifactError(f"cannot read tarball {path}: {exc}") from exc
    name, version, description = _parse_metadata(text, path)
    return Artifact(path, "sdist", name, version, description, tuple(members))


def _collection(
    path: Path, archive: tarfile.TarFile, members: tuple[str, ...]
) -> Artifact:
    try:
        data = json.loads(_extract(archive, "MANIFEST.json", path))
        info = data["collection_info"]
        name = f"{info['namespace']}.{info['name']}"
        version = str(info["version"])
        readme = str(info.get("readme") or "README.md")
    except (KeyError, TypeError, ValueError) as exc:
        raise ArtifactError(
            f"{path.name}: MANIFEST.json lacks collection_info"
        ) from exc
    description = (
        _extract(archive, readme, path).decode("utf-8", errors="replace")
        if readme in members
        else ""
    )
    return Artifact(path, "collection", name, version, description, members)


def _extract(archive: tarfile.TarFile, member: str, path: Path) -> bytes:
    stream = archive.extractfile(member)
    if stream is None:
        raise ArtifactError(f"{path.name}: cannot read {member}")
    with stream:
        return stream.read()


def _parse_metadata(text: str, path: Path) -> tuple[str, str, str]:
    headers, _, description = text.partition("\n\n")
    fields: dict[str, str] = {}
    for line in headers.splitlines():
        key, separator, value = line.partition(":")
        if separator and key and key[0] != " ":
            fields.setdefault(key.strip().lower(), value.strip())
    name, version = fields.get("name"), fields.get("version")
    if not name or not version:
        raise ArtifactError(f"{path.name}: metadata lacks Name or Version")
    if fields.get("description-content-type", "").split(";")[0].strip() not in (
        "",
        "text/markdown",
    ):
        description = ""
    return name, version, description


def _member_problems(member: str) -> list[str]:
    if "\x00" in member or "\\" in member:
        return [f"unsafe member name {member!r}"]
    parts = PurePosixPath(member).parts
    if PurePosixPath(member).is_absolute() or any(
        part in {"", ".", ".."} for part in parts
    ):
        return [f"unsafe member path {member!r}"]
    problems = []
    if any(
        part in _FORBIDDEN_PARTS or (part.startswith(".") and "cache" in part)
        for part in parts
    ):
        problems.append(f"contains generated path {member}")
    elif (
        parts
        and parts[-1] not in _EXPECTED_NAMES
        and (
            parts[-1] in _FORBIDDEN_NAMES
            or PurePosixPath(parts[-1]).suffix in _FORBIDDEN_SUFFIXES
        )
    ):
        problems.append(f"contains generated file {member}")
    return problems


def _description_problems(artifact: Artifact) -> list[str]:
    if not artifact.description.strip():
        return ["description is empty; the index page would be blank"]
    try:
        document = markdown.analyze(artifact.description)
    except ValueError as exc:
        return [f"description is not parseable Markdown: {exc}"]
    relative = [
        destination.value
        for destination in document.destinations
        if markdown.is_local(destination.value)
    ]
    if relative:
        shown = ", ".join(repr(value) for value in relative[:5])
        more = "" if len(relative) <= 5 else f" and {len(relative) - 5} more"
        return [
            f"description has {len(relative)} relative destination(s) that break on "
            f"the index: {shown}{more}; prepare the README before building"
        ]
    return []
