# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later
"""Keep a Changelog files: check their structure, show a section, release one.

The supported layout is the one the foundata projects use: a ``## [Unreleased]``
section first, then ``## [X.Y.Z] - YYYY-MM-DD`` sections newest first, and at
the end one link definition per version plus ``[unreleased]`` pointing at the
forge's comparison between the latest tag and ``HEAD``. Text is edited line by
line; nothing else in the file is reformatted. Nothing here runs Git or
another program.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime

from releasing.forges import Forge
from releasing.version import is_prerelease, is_version

PLACEHOLDER = "- Nothing worth mentioning right now."
_HEADING = re.compile(r"^## \[(?P<label>[^\]]+)\](?: - (?P<date>\S+))?[ \t]*$")
_DEFINITION = re.compile(r"^\[(?P<label>[^\]]+)\]:[ \t]*(?P<url>\S+)[ \t]*$")
_EMPTY = re.compile(r"^-?[ \t]*(nothing|no unreleased|none)\b", re.IGNORECASE)
_FENCE = re.compile(r"^(```|~~~)")


class ChangelogError(ValueError):
    """The changelog is malformed or does not fit the requested operation."""


@dataclass(frozen=True)
class Section:
    """One ``##`` section: its label, date, heading line and body lines."""

    label: str
    date: str | None
    line: int
    body: tuple[str, ...]

    @property
    def unreleased(self) -> bool:
        """Whether this is the ``Unreleased`` section."""
        return self.label.lower() == "unreleased"

    @property
    def text(self) -> str:
        """The body without leading or trailing blank lines."""
        lines = list(self.body)
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        return "\n".join(lines) + ("\n" if lines else "")


@dataclass(frozen=True)
class Changelog:
    """The parsed sections and link definitions of one file."""

    sections: tuple[Section, ...]
    definitions: dict[str, tuple[int, str]]
    newline: str
    lines: tuple[str, ...]


def parse(text: str) -> Changelog:
    """Split the file into sections and link definitions; code blocks are opaque."""
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines()
    sections: list[Section] = []
    definitions: dict[str, tuple[int, str]] = {}
    headings: list[tuple[int, str, str | None]] = []
    fenced = False
    for number, line in enumerate(lines, start=1):
        if _FENCE.match(line):
            fenced = not fenced
            continue
        if fenced:
            continue
        heading = _HEADING.match(line)
        if heading is not None:
            headings.append((number, heading["label"], heading["date"]))
            continue
        definition = _DEFINITION.match(line)
        if definition is not None:
            definitions.setdefault(
                definition["label"].lower(), (number, definition["url"])
            )
    for index, (number, label, when) in enumerate(headings):
        end = headings[index + 1][0] - 1 if index + 1 < len(headings) else len(lines)
        body = lines[number:end]
        while body and _DEFINITION.match(body[-1]):
            body.pop()
        sections.append(Section(label, when, number, tuple(body)))
    return Changelog(tuple(sections), definitions, newline, tuple(lines))


def show(text: str, version: str) -> str:
    """Return the body of one version's section (or ``Unreleased``)."""
    wanted = version.lower()
    for section in parse(text).sections:
        if section.label.lower() == wanted:
            return section.text
    raise ChangelogError(f"no changelog section for {version}")


def check(
    text: str,
    *,
    forge: Forge,
    tag_format: str,
    version: str | None = None,
    today: date | None = None,
) -> list[str]:
    """Return every structural problem, and for ``version`` that it is the latest release.

    ``today`` is the day a release date may not lie after; it defaults to the
    machine's date and exists so a test can pin it.
    """
    changelog = parse(text)
    limit = today or _today()
    problems: list[str] = []
    sections = changelog.sections
    if not sections or not sections[0].unreleased:
        problems.append("the first section must be ## [Unreleased]")
    released = [section for section in sections if not section.unreleased]
    seen: set[str] = set()
    previous: tuple[int, ...] | None = None
    for section in released:
        where = f"line {section.line}: [{section.label}]"
        if not is_version(section.label):
            problems.append(f"{where}: not a version")
            continue
        if section.date is None or not _valid_date(section.date):
            problems.append(f"{where}: needs a release date as YYYY-MM-DD")
        elif date.fromisoformat(section.date) > limit:
            problems.append(f"{where}: release date {section.date} is in the future")
        if section.label in seen:
            problems.append(f"{where}: duplicate section")
        seen.add(section.label)
        key = _key(section.label)
        if previous is not None and key >= previous:
            problems.append(f"{where}: sections must be newest first")
        previous = key
        if section.label.lower() not in changelog.definitions:
            problems.append(f"{where}: no link definition [{section.label}]: URL")
    if released and all(is_version(section.label) for section in released):
        latest = tag_format.format(version=released[0].label)
        expected = forge.compare_url(latest, "HEAD")
        unreleased = changelog.definitions.get("unreleased")
        if unreleased is None:
            problems.append(f"missing link definition [unreleased]: {expected}")
        elif unreleased[1] != expected:
            problems.append(
                f"line {unreleased[0]}: [unreleased] must compare {latest}...HEAD: {expected}"
            )
    # A pre-release is not a release: it needs no dated section of its own, and
    # a project before its first release has none at all.
    if version is not None and not is_prerelease(version):
        if not released or released[0].label != version:
            problems.append(f"the latest released section must be [{version}]")
    return problems


def release(
    text: str,
    version: str,
    *,
    forge: Forge,
    tag_format: str,
    when: date | None = None,
    placeholder: str = PLACEHOLDER,
) -> str:
    """Turn the Unreleased entries into the section for ``version``.

    The Unreleased heading becomes ``## [version] - date``, a fresh Unreleased
    section with the placeholder goes above it, the ``[unreleased]`` link
    compares the new tag with ``HEAD`` and a tag link for the version is
    inserted after it. Raise ChangelogError when there is nothing to release,
    the version already exists or is not newer than the latest one.
    """
    if not is_version(version):
        raise ChangelogError(f"not a version: {version!r}")
    changelog = parse(text)
    problems = check(text, forge=forge, tag_format=tag_format)
    if problems:
        raise ChangelogError("\n".join(problems))
    unreleased = changelog.sections[0]
    entries = [line for line in unreleased.body if line.strip()]
    if not entries or (len(entries) == 1 and _EMPTY.match(entries[0])):
        raise ChangelogError("nothing to release: no entries under [Unreleased]")
    released = changelog.sections[1:]
    if any(section.label == version for section in released):
        raise ChangelogError(f"section [{version}] already exists")
    if released and _key(version) <= _key(released[0].label):
        raise ChangelogError(
            f"{version} is not newer than the latest release {released[0].label}"
        )
    tag = tag_format.format(version=version)
    day = (when or _today()).isoformat()
    gap = _trailing_blank_lines(unreleased.body) or 2
    lines = list(changelog.lines)
    heading = unreleased.line - 1
    lines[heading : heading + 1] = [
        "## [Unreleased]",
        "",
        placeholder,
        *([""] * gap),
        f"## [{version}] - {day}",
    ]
    inserted = 3 + gap  # one heading line became 4 + gap lines
    definition = changelog.definitions.get("unreleased")
    compare = forge.compare_url(tag, "HEAD")
    tag_link = f"[{version}]: {forge.tag_url(tag)}"
    if definition is None:
        while lines and not lines[-1].strip():
            lines.pop()
        lines.extend(["", f"[unreleased]: {compare}", tag_link])
    else:
        number = definition[0] - 1 + inserted
        original = lines[number]
        label = original[: original.index("]") + 1]
        lines[number : number + 1] = [f"{label}: {compare}", tag_link]
    result = changelog.newline.join(lines)
    return result + changelog.newline if text.endswith(("\n", "\r")) else result


def antsibull_has_release(changelog_yaml: str, version: str) -> bool:
    """Whether antsibull's ``changelogs/changelog.yaml`` lists ``version`` under releases."""
    return (
        re.search(
            r"^  " + re.escape(version) + r":[ \t]*$", changelog_yaml, re.MULTILINE
        )
        is not None
    )


def _today() -> date:
    return datetime.now().astimezone().date()


def _valid_date(value: str) -> bool:
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _key(version: str) -> tuple[int, ...]:
    match = re.match(r"(\d+)\.(\d+)\.(\d+)(.*)", version)
    assert match is not None, version  # callers pass validated versions only
    numbers = tuple(int(part) for part in match.groups()[:3])
    # A pre-release sorts below its final version.
    return (*numbers, 0 if match.group(4) else 1)


def _trailing_blank_lines(body: tuple[str, ...]) -> int:
    count = 0
    for line in reversed(body):
        if line.strip():
            break
        count += 1
    return count
