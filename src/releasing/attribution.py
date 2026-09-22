# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later
"""Refuse to publish a commit that credits a tool as its author.

A commit message is a technical record of the work, not of the tooling used to
produce it. The check runs where a commit is about to become public and can
still be amended for free, because once it is pushed the only remedy is a
history rewrite.

What is read is narrow on purpose: the identity fields, the value of a
``Co-authored-by:`` or ``Assisted-by:`` trailer, and the phrases the common
tools sign their work with. A vendor name in the prose of a message is not a
finding, so documenting an integration and releasing a project about AI both
stay possible.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from releasing import processes

IDENTITY = "identity"
CO_AUTHORED_BY = "co-authored-by"
ASSISTED_BY = "assisted-by"
GENERATED_WITH = "generated-with"
RULES = (IDENTITY, CO_AUTHORED_BY, ASSISTED_BY, GENERATED_WITH)

# Identities, not vendor names: a person who works at one of these companies
# commits under their own address and is not a finding.
_TOOL_IDENTITIES = (
    re.compile(r"<[^>]*noreply@anthropic\.com>", re.IGNORECASE),
    re.compile(r"<[^>]*claude[^>]*@anthropic\.com>", re.IGNORECASE),
    re.compile(r"<[^>]*copilot@github\.com>", re.IGNORECASE),
    re.compile(r"<\d+\+copilot@users\.noreply\.github\.com>", re.IGNORECASE),
    re.compile(r"<[^>]*@cursor\.(com|sh)>", re.IGNORECASE),
    re.compile(r"\bdevin-ai-integration\[bot\]", re.IGNORECASE),
    re.compile(r"\bgoogle-labs-jules\[bot\]", re.IGNORECASE),
    re.compile(r"\bgemini-code-assist\[bot\]", re.IGNORECASE),
    re.compile(r"\bcodex\[bot\]", re.IGNORECASE),
)
_CO_AUTHORED_BY = re.compile(r"^\s*co-authored-by:\s*(?P<value>.+)$", re.IGNORECASE)
_ASSISTED_BY = re.compile(r"^\s*assisted-by:\s*(?P<value>.+)$", re.IGNORECASE)
_GENERATED_WITH = re.compile(r"generated with|\U0001f916", re.IGNORECASE)

# The separators are written as git placeholders, not as literal bytes: an
# argument list cannot carry a NUL.
_SEPARATOR = "\x00"
_END = "\x01"
_FORMAT = "--format=%H%x00%s%x00%an <%ae>%x00%cn <%ce>%x00%B%x01"


class AttributionError(RuntimeError):
    """The commits could not be read."""


@dataclass(frozen=True)
class Commit:
    """One commit, as far as this check needs to know it."""

    revision: str
    subject: str
    author: str
    committer: str
    message: str


@dataclass(frozen=True)
class Finding:
    """One reason a commit may not be published as it stands."""

    revision: str
    subject: str
    rule: str
    evidence: str


@dataclass(frozen=True)
class Allowance:
    """One attribution a project carries on purpose."""

    rule: str
    pattern: re.Pattern[str] | None

    def permits(self, rule: str, evidence: str) -> bool:
        """Whether this allowance covers one finding."""
        if rule != self.rule:
            return False
        return self.pattern is None or bool(self.pattern.search(evidence))


def allowance(entry: str) -> Allowance:
    """Read one ``allowed-attribution`` entry, raising ValueError on nonsense.

    An entry is a rule name, which allows the whole rule, or a rule name and a
    regular expression separated by a colon, which allows the values that
    expression finds. The shape is the one an error prints, so a finding can be
    copied into the declaration and narrowed there.
    """
    rule, separator, pattern = entry.partition(":")
    rule = rule.strip()
    if rule not in RULES:
        raise ValueError(f"must name a known rule ({', '.join(RULES)}): {entry!r}")
    if not separator or not pattern.strip():
        return Allowance(rule, None)
    try:
        return Allowance(rule, re.compile(pattern.strip(), re.IGNORECASE))
    except re.error as exc:
        raise ValueError(f"has an unusable pattern ({exc}): {entry!r}") from exc


def findings(
    commits: Iterable[Commit], *, allowed: Iterable[str] = ()
) -> list[Finding]:
    """Every attribution in ``commits`` a project has not allowed."""
    allowances = [allowance(entry) for entry in allowed]
    found: list[Finding] = []
    for commit in commits:
        for rule, evidence in _inspect(commit):
            if any(item.permits(rule, evidence) for item in allowances):
                continue
            found.append(Finding(commit.revision, commit.subject, rule, evidence))
    return found


def _inspect(commit: Commit) -> list[tuple[str, str]]:
    """What one commit says, each distinct finding once.

    The author and the committer are usually the same person, and reporting a
    line twice for one identity reads like two separate problems.
    """
    found: list[tuple[str, str]] = []
    for identity in (commit.author, commit.committer):
        if _is_tool(identity):
            found.append((IDENTITY, identity))
    for line in commit.message.splitlines():
        co_authored = _CO_AUTHORED_BY.match(line)
        if co_authored and _is_tool(co_authored.group("value")):
            found.append((CO_AUTHORED_BY, co_authored.group("value").strip()))
            continue
        assisted = _ASSISTED_BY.match(line)
        if assisted:
            found.append((ASSISTED_BY, assisted.group("value").strip()))
            continue
        if _GENERATED_WITH.search(line):
            found.append((GENERATED_WITH, line.strip()))
    return list(dict.fromkeys(found))


def _is_tool(identity: str) -> bool:
    return any(pattern.search(identity) for pattern in _TOOL_IDENTITIES)


def read(root: Path, revisions: Sequence[str]) -> list[Commit]:
    """Read every commit ``revisions`` selects.

    A selector is either one commit or a ``a..b`` range. The two are read
    separately, because a single revision must not drag its ancestors in while
    a range must. Duplicates are collapsed: a release commit is both the tagged
    revision and part of what the push would send.
    """
    ranges = [item for item in revisions if ".." in item]
    singles = [item for item in revisions if ".." not in item]
    records: list[str] = []
    if singles:
        records += _log(root, ["--no-walk", *singles])
    if ranges:
        records += _log(root, list(ranges))
    seen: dict[str, Commit] = {}
    for record in records:
        fields = record.strip("\n\x00").split(_SEPARATOR)
        if len(fields) != 5 or not fields[0].strip():
            continue
        revision, subject, author, committer, message = (
            field.strip("\n\x00") for field in fields
        )
        seen.setdefault(
            revision,
            Commit(
                revision=revision,
                subject=subject,
                author=author,
                committer=committer,
                message=message,
            ),
        )
    return list(seen.values())


def _log(root: Path, selectors: Sequence[str]) -> list[str]:
    try:
        output = processes.git(
            root,
            "log",
            _FORMAT,
            *selectors,
            "--",
        )
    except processes.ProcessError as exc:
        raise AttributionError(f"cannot read the commits to check: {exc}") from exc
    return output.split(_END)


def describe(found: Sequence[Finding]) -> list[str]:
    """The problem lines for an error, one per finding, grouped by commit."""
    lines: list[str] = []
    current = ""
    for finding in found:
        if finding.revision != current:
            current = finding.revision
            lines.append(f"{finding.revision[:12]} {finding.subject}")
        lines.append(f"  {finding.rule}: {finding.evidence}")
    return lines
