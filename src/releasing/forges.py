# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later
"""Forge backends: where tags, releases and file contents of a repository live.

A forge knows the URLs of a repository's pages and, for the commands that talk
to it, its release API: the paths to ask, the command-line tool that asks and
writes with the user's own login, and the environment variables a token
arrives in. GitHub is the first implementation; a Gitea, Forgejo or GitLab
backend is a new entry here, selected by the declaration's ``forge`` key.
Nothing in this module performs network access.
"""

from dataclasses import dataclass

from releasing.config import ReleaseConfig


@dataclass(frozen=True)
class Forge:
    """URL patterns, API paths and the client of one forge for one repository.

    ``tool`` is the forge's own command-line program, which carries the user's
    login; ``token_variables`` name the environment variables a token is read
    from, first match wins. A forge without a tool is asked anonymously or
    with a token only, and gets no release entry written.
    """

    name: str
    repository: str
    web: str
    raw: str
    api: str
    tool: str | None = None
    token_variables: tuple[str, ...] = ()

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

    def raw_base(self, ref: str) -> str:
        """URL base for file contents at ``ref``, used for image destinations."""
        return f"{self.raw}/{self.repository}/{ref}"

    def blob_base(self, ref: str) -> str:
        """URL base for the file viewer at ``ref``, used for link destinations."""
        return f"{self.repository_url()}/blob/{ref}"

    def latest_release_path(self) -> str:
        """API path, below ``api``, of the release the forge considers latest."""
        return f"repos/{self.repository}/releases/latest"

    def release_by_tag_path(self, tag: str) -> str:
        """API path, below ``api``, of the release belonging to one tag."""
        return f"repos/{self.repository}/releases/tags/{tag}"

    def latest_release_url(self) -> str:
        """API endpoint reporting the release the forge considers latest."""
        return f"{self.api}/{self.latest_release_path()}"

    def release_by_tag_url(self, tag: str) -> str:
        """API endpoint for the release belonging to one tag."""
        return f"{self.api}/{self.release_by_tag_path(tag)}"


_FORGES: dict[str, dict[str, object]] = {
    "github": {
        "web": "https://github.com",
        "raw": "https://raw.githubusercontent.com",
        "api": "https://api.github.com",
        "tool": "gh",
        # gh's own variable first; GITHUB_TOKEN is what GitHub Actions sets.
        "token_variables": ("GH_TOKEN", "GITHUB_TOKEN"),
    }
}


def forge_for(config: ReleaseConfig) -> Forge:
    """The forge backend selected by the declaration."""
    try:
        definition = _FORGES[config.forge]
    except KeyError as exc:
        raise ValueError(f"unsupported forge: {config.forge}") from exc
    return Forge(name=config.forge, repository=config.repository, **definition)  # type: ignore[arg-type]
