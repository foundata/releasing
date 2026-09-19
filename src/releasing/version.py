# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later
"""Version sites: find, compare and rewrite every place a project states its version.

A site is one line in a declared file whose key is ``version``,
``__version__``, ``VERSION`` or ``"productVersion"``, followed by ``=`` or
``:`` and the version, optionally quoted, optionally followed by a comma. Each
declared file must contain exactly one such line, so a file whose spelling
drifted is an error rather than a silent skip. Nothing here runs Git or another
program; the command layer adds the tag and working-tree facts.
"""

import re
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from releasing.config import DependencyPin, ReleaseConfig

VERSION = re.compile(r"\d+\.\d+\.\d+(?:(?:-|\.)?(?:a|b|rc|alpha|beta|dev)\.?\d*)?")
_SITE = re.compile(
    r'^(?P<prefix>[ \t]*(?:"productVersion"|__version__|VERSION|version)[ \t]*[:=][ \t]*)'
    r"(?P<quote>[\"']?)(?P<version>" + VERSION.pattern + r")(?P=quote)"
    r"(?P<suffix>,?[ \t]*)$"
)


class VersionError(ValueError):
    """Version sites are missing, ambiguous or disagree."""


@dataclass(frozen=True)
class Site:
    """One version statement: file, one-based line number and the value."""

    file: str
    line: int
    version: str


def is_version(value: str) -> bool:
    """Whether ``value`` is a version this package accepts (``X.Y.Z`` plus pre-release)."""
    return VERSION.fullmatch(value) is not None


def find_sites(root: Path, config: ReleaseConfig) -> list[Site]:
    """Locate the single version site in every declared file.

    Raise VersionError naming every file with no site or more than one.
    """
    sites: list[Site] = []
    problems: list[str] = []
    for file in config.version_files:
        matches = [
            Site(file, number, match["version"])
            for number, line in enumerate(_lines(root / file), start=1)
            if (match := _SITE.match(line)) is not None
        ]
        if len(matches) != 1:
            problems.append(
                f"{file}: expected exactly one version line, found {len(matches)}"
            )
        sites.extend(matches)
    if problems:
        raise VersionError("\n".join(problems))
    return sites


def locked_versions(root: Path) -> dict[str, str]:
    """Package versions recorded in ``uv.lock`` below ``root``, or empty without one."""
    lock = root / "uv.lock"
    if not lock.is_file():
        return {}
    try:
        data = tomllib.loads(lock.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise VersionError(f"cannot read {lock}: {exc}") from exc
    packages = data.get("package", [])
    if not isinstance(packages, list):
        raise VersionError(f"{lock}: package entries must be an array")
    versions: dict[str, str] = {}
    for entry in packages:
        if isinstance(entry, dict) and isinstance(entry.get("name"), str):
            versions[str(entry["name"])] = str(entry.get("version", ""))
    return versions


def project_names(root: Path, config: ReleaseConfig) -> dict[str, str]:
    """Map each declared ``pyproject.toml`` that has ``[project]`` to its name."""
    names: dict[str, str] = {}
    for file in config.version_files:
        if Path(file).name != "pyproject.toml":
            continue
        try:
            data = tomllib.loads((root / file).read_text(encoding="utf-8"))
        except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
            raise VersionError(f"cannot read {file}: {exc}") from exc
        project = data.get("project")
        if isinstance(project, dict) and isinstance(project.get("name"), str):
            names[file] = str(project["name"])
    return names


def check(
    root: Path,
    config: ReleaseConfig,
    *,
    expect: str | None = None,
    tags_on_head: Sequence[str] | None = None,
) -> str:
    """Return the one version every site agrees on, or raise VersionError.

    ``expect`` is compared against that version. ``tags_on_head`` are the tags
    pointing at the current revision; when given and non-empty, the release tag
    for the version must be among them. The lockfile, when present, must record
    the same version for every declared project.
    """
    sites = find_sites(root, config)
    problems: list[str] = []
    versions = sorted({site.version for site in sites})
    if len(versions) > 1:
        problems.extend(f"{site.file}:{site.line}: {site.version}" for site in sites)
        problems.insert(0, "version sites disagree:")
    version = versions[0] if versions else (expect or "")
    if expect is not None and version != expect:
        problems.append(f"expected {expect}, sites state {version}")
    if version:
        locked = locked_versions(root)
        for file, name in project_names(root, config).items():
            if name in locked and locked[name] != version:
                problems.append(
                    f"uv.lock records {name} {locked[name]} but {file} states {version}; run uv lock"
                )
        for pin in config.dependency_pins:
            bound = _pin_bound(root, pin)
            if bound != version:
                problems.append(
                    f"{pin.file}: {pin.name} lower bound is {bound}, expected {version}"
                )
        if tags_on_head:
            tag = config.tag(version)
            if tag not in tags_on_head:
                problems.append(
                    f"tag {tag} does not point at the current revision "
                    f"(tags here: {', '.join(tags_on_head)})"
                )
    if problems:
        raise VersionError("\n".join(problems))
    return version


@dataclass(frozen=True)
class Edit:
    """One file rewritten by a bump, with its content before and after."""

    file: str
    before: str
    after: str


def bump(root: Path, config: ReleaseConfig, new_version: str) -> list[Edit]:
    """Rewrite every site and every lockstep pin to ``new_version``; return the edits.

    The current version is taken from the sites, which must agree. Files are
    written only after every edit has been computed. Quoting, spacing, line
    endings and trailing commas are preserved. The changelog and lockfile are
    not touched.
    """
    if not is_version(new_version):
        raise VersionError(f"not a version: {new_version!r}")
    old_version = check(root, config)
    if old_version == new_version:
        raise VersionError(f"sites already state {new_version}")
    before: dict[str, str] = {}
    after: dict[str, str] = {}

    def current(file: str) -> str:
        if file not in before:
            before[file] = after[file] = _read(root / file)
        return after[file]

    for site in find_sites(root, config):
        lines = current(site.file).splitlines(keepends=True)
        line = lines[site.line - 1]
        ending = line[len(line.rstrip("\r\n")) :]
        match = _SITE.match(line.rstrip("\r\n"))
        assert match is not None
        lines[site.line - 1] = (
            match["prefix"]
            + match["quote"]
            + new_version
            + match["quote"]
            + match["suffix"]
            + ending
        )
        after[site.file] = "".join(lines)
    for pin in config.dependency_pins:
        pattern = _pin_pattern(pin)
        text = current(pin.file)
        if len(pattern.findall(text)) != 1:
            raise VersionError(
                f"{pin.file}: expected exactly one {pin.name} lower bound"
            )
        after[pin.file] = pattern.sub(
            lambda m: m["prefix"] + new_version + m["suffix"], text
        )
    edits = [Edit(file, before[file], after[file]) for file in before]
    for edit in edits:
        (root / edit.file).write_text(edit.after, encoding="utf-8", newline="")
    return edits


def _pin_pattern(pin: DependencyPin) -> re.Pattern[str]:
    return re.compile(
        r"(?P<prefix>[\"']"
        + re.escape(pin.name)
        + r"[ \t]*>=[ \t]*)(?P<version>"
        + VERSION.pattern
        + r")(?P<suffix>[ \t]*,[ \t]*<[^\"']*[\"'])"
    )


def _pin_bound(root: Path, pin: DependencyPin) -> str:
    matches = _pin_pattern(pin).findall(_read(root / pin.file))
    if len(matches) != 1:
        raise VersionError(
            f'{pin.file}: expected exactly one "{pin.name}>=X.Y.Z,<N" requirement, '
            f"found {len(matches)}"
        )
    return str(matches[0][1])


def _read(path: Path) -> str:
    try:
        # Keep line endings as they are; Path.read_text(newline=...) needs 3.13.
        with path.open(encoding="utf-8", newline="") as stream:
            return stream.read()
    except (OSError, UnicodeError) as exc:
        raise VersionError(f"cannot read {path}: {exc}") from exc


def _lines(path: Path) -> list[str]:
    return _read(path).splitlines()
