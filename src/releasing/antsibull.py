# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later
"""Release notes for a collection, read from antsibull-changelog's own data.

antsibull-changelog owns a collection's changelog: it collects fragments,
assigns them to a release and renders the file. This reads the result for one
version and renders it as Markdown for a forge release entry. It never writes
that data and never decides what belongs in a release.

Section titles come from ``changelogs/config.yaml`` where a project sets them,
so the notes read the same as the rendered changelog. Entry text is passed
through as written, except that RST inline literals become Markdown code
spans; other markup a fragment may contain is left alone.
"""

import re
from pathlib import Path
from typing import Any

CHANGES = Path("changelogs") / "changelog.yaml"
CONFIG = Path("changelogs") / "config.yaml"
PRELUDE = "release_summary"
# antsibull-changelog's defaults, used when a project sets none of its own.
DEFAULT_PRELUDE_TITLE = "Release Summary"
DEFAULT_SECTIONS: tuple[tuple[str, str], ...] = (
    ("major_changes", "Major Changes"),
    ("minor_changes", "Minor Changes"),
    ("breaking_changes", "Breaking Changes / Porting Guide"),
    ("deprecated_features", "Deprecated Features"),
    ("removed_features", "Removed Features (previously deprecated)"),
    ("security_fixes", "Security Fixes"),
    ("bugfixes", "Bugfixes"),
    ("known_issues", "Known Issues"),
)
_LITERAL = re.compile(r"``([^`]+)``")


class AntsibullError(ValueError):
    """The collection's changelog data cannot be read or lacks the version."""


def _yaml() -> Any:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - only a broken installation
        raise AntsibullError(
            "reading a collection changelog needs PyYAML, which this package "
            "depends on; the installation looks incomplete"
        ) from exc
    return yaml


def _load(path: Path) -> Any:
    yaml = _yaml()
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as exc:
        raise AntsibullError(f"cannot read {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise AntsibullError(f"{path} is not valid YAML: {exc}") from exc


def section_titles(root: Path) -> tuple[str, tuple[tuple[str, str], ...]]:
    """The prelude title and ordered section titles this project uses."""
    path = root / CONFIG
    if not path.is_file():
        return DEFAULT_PRELUDE_TITLE, DEFAULT_SECTIONS
    document = _load(path)
    if not isinstance(document, dict):
        raise AntsibullError(f"{CONFIG}: expected a mapping")
    prelude = document.get("prelude_section_title") or DEFAULT_PRELUDE_TITLE
    declared = document.get("sections")
    if not isinstance(declared, list):
        return str(prelude), DEFAULT_SECTIONS
    sections = tuple(
        (str(entry[0]), str(entry[1]))
        for entry in declared
        if isinstance(entry, list | tuple) and len(entry) == 2
    )
    return str(prelude), sections or DEFAULT_SECTIONS


def release_entry(root: Path, version: str) -> dict[str, Any]:
    """The recorded entry for one version, or raise AntsibullError."""
    document = _load(root / CHANGES)
    releases = document.get("releases") if isinstance(document, dict) else None
    if not isinstance(releases, dict):
        raise AntsibullError(f"{CHANGES}: expected a releases mapping")
    entry = releases.get(version)
    if entry is None:
        raise AntsibullError(f"{CHANGES} has no release {version}")
    if not isinstance(entry, dict):
        raise AntsibullError(f"{CHANGES}: release {version} is not a mapping")
    return entry


def notes(root: Path, version: str) -> str:
    """Render one version's recorded changes as Markdown."""
    entry = release_entry(root, version)
    prelude_title, sections = section_titles(root)
    changes = entry.get("changes")
    changes = changes if isinstance(changes, dict) else {}
    parts: list[str] = []
    summary = changes.get(PRELUDE)
    if isinstance(summary, str) and summary.strip():
        parts.append(f"### {prelude_title}\n\n{_text(summary)}\n")
    for name, title in sections:
        items = changes.get(name)
        if not isinstance(items, list) or not items:
            continue
        rendered = "\n".join(f"- {_text(str(item))}" for item in items)
        parts.append(f"### {title}\n\n{rendered}\n")
    parts.extend(_new_content(entry))
    if not parts:
        raise AntsibullError(f"{CHANGES}: release {version} records no changes")
    return "\n".join(parts)


def _new_content(entry: dict[str, Any]) -> list[str]:
    parts: list[str] = []
    modules = entry.get("modules")
    if isinstance(modules, list) and modules:
        parts.append("### New Modules\n\n" + _describe(modules) + "\n")
    plugins = entry.get("plugins")
    if isinstance(plugins, dict):
        for kind in sorted(plugins):
            listed = plugins[kind]
            if isinstance(listed, list) and listed:
                title = f"New {str(kind).replace('_', ' ').title()} Plugins"
                parts.append(f"### {title}\n\n" + _describe(listed) + "\n")
    return parts


def _describe(listed: list[Any]) -> str:
    lines = []
    for item in listed:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        description = str(item.get("description") or "").strip()
        name = str(item["name"])
        lines.append(f"- {name} - {_text(description)}" if description else f"- {name}")
    return "\n".join(lines)


def _text(value: str) -> str:
    # antsibull fragments are written for reStructuredText; only the inline
    # literal has a Markdown equivalent obvious enough to translate.
    return _LITERAL.sub(r"`\1`", value.strip())
