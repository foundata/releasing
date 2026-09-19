# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later
"""Forge backends: where tags, releases and comparison pages live.

A forge knows the URLs of a repository's pages and, in later commands, whether
a release exists for a tag. GitHub is the first implementation; a Gitea,
Forgejo or GitLab backend is a new class here, selected by the declaration's
``forge`` key. Nothing in this module performs network access.
"""

from dataclasses import dataclass

from releasing.config import ReleaseConfig


@dataclass(frozen=True)
class Forge:
    """URL patterns of one forge for one repository."""

    name: str
    repository: str
    web: str

    def repository_url(self) -> str:
        """The repository's landing page."""
        return f"{self.web}/{self.repository}"

    def tag_url(self, tag: str) -> str:
        """The page a changelog links a released version to."""
        return f"{self.repository_url()}/releases/tag/{tag}"

    def compare_url(self, base: str, head: str) -> str:
        """The page comparing two refs, used for the unreleased changelog link."""
        return f"{self.repository_url()}/compare/{base}...{head}"

    def releases_url(self) -> str:
        """The releases listing."""
        return f"{self.repository_url()}/releases"


_WEB = {"github": "https://github.com"}


def forge_for(config: ReleaseConfig) -> Forge:
    """The forge backend selected by the declaration."""
    try:
        web = _WEB[config.forge]
    except KeyError as exc:
        raise ValueError(f"unsupported forge: {config.forge}") from exc
    return Forge(name=config.forge, repository=config.repository, web=web)
