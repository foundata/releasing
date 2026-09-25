# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later
"""The release declaration shared by project-aware commands.

The declaration lives in ``[tool.releasing]`` of ``pyproject.toml`` or, for
repositories without one, at the top level of ``releasing.toml`` or
``.releasing.toml``. Every default is what foundata uses; an adopter overrides
them in the same table. Loading never runs Git or external programs, so it
works in an exported tree.
"""

import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from releasing import attribution

PYPROJECT = "pyproject.toml"
STANDALONES = ("releasing.toml", ".releasing.toml")
FORGES = ("github",)
INDEXES = ("pypi", "galaxy", "none")
ECOSYSTEMS = ("python", "ansible-collection", "hugo-component")
CHANGELOG_FORMATS = ("keep-a-changelog", "antsibull")
_REPOSITORY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*")
_ECOSYSTEM_DEFAULTS: dict[str, dict[str, object]] = {
    "python": {"index": "pypi", "version-files": ["pyproject.toml"]},
    "ansible-collection": {
        "index": "galaxy",
        "version-files": ["galaxy.yml"],
        "changelog": "antsibull",
    },
    "hugo-component": {"index": "none", "version-files": []},
}
_KEYS = frozenset(
    {
        "repository",
        "forge",
        "index",
        "ecosystem",
        "version-files",
        "changelog",
        "tag-format",
        "tag-message",
        "dependency-pins",
        "readmes",
        "allowed-attribution",
    }
)
_README_KEYS = frozenset(
    {"source-path", "ref", "simplify-badges", "collapse-header", "copies"}
)
_PIN_KEYS = frozenset({"file", "name"})


class ConfigError(ValueError):
    """The declaration is missing, ambiguous or invalid."""


@dataclass(frozen=True)
class ReadmeConfig:
    """One Markdown document prepared for a package index."""

    source_path: str = "README.md"
    ref: str = "refs/tags/{tag}"
    simplify_badges: bool = False
    collapse_header: bool = False
    copies: tuple[str, ...] = ()


@dataclass(frozen=True)
class DependencyPin:
    """A requirement whose lower bound follows the project's own version."""

    file: str
    name: str


@dataclass(frozen=True)
class ReleaseConfig:
    """A validated release declaration with every default applied."""

    root: Path
    source: Path
    repository: str
    forge: str = "github"
    index: str = "pypi"
    ecosystem: str = "python"
    version_files: tuple[str, ...] = ("pyproject.toml",)
    changelog: str = "CHANGELOG.md"
    tag_format: str = "v{version}"
    tag_message: str = "version {version}"
    dependency_pins: tuple[DependencyPin, ...] = ()
    allowed_attribution: tuple[str, ...] = ()
    readmes: tuple[ReadmeConfig, ...] = field(default_factory=lambda: (ReadmeConfig(),))

    @property
    def owner(self) -> str:
        """The forge account or organization owning the repository."""
        return self.repository.partition("/")[0]

    @property
    def name(self) -> str:
        """The repository name on the forge."""
        return self.repository.partition("/")[2]

    @property
    def changelog_path(self) -> str:
        """The file the changelog is kept in, whichever format owns it."""
        if self.changelog_format == "antsibull":
            return "changelogs/changelog.yaml"
        return self.changelog

    @property
    def changelog_format(self) -> str:
        """``keep-a-changelog`` for a Markdown file, ``antsibull`` otherwise."""
        return "antsibull" if self.changelog == "antsibull" else "keep-a-changelog"

    def tag(self, version: str) -> str:
        """The tag name for a version, from ``tag-format``."""
        return self.tag_format.format(version=version)

    def tag_message_for(self, version: str) -> str:
        """The annotated tag message for a version, from ``tag-message``."""
        return self.tag_message.format(version=version, tag=self.tag(version))


def locate(root: Path) -> tuple[Path, Mapping[str, object]]:
    """Find the declaration table below ``root`` without validating it.

    Raise ConfigError when no file declares it or more than one does.
    """
    candidates: list[tuple[Path, Mapping[str, object]]] = []
    pyproject = root / PYPROJECT
    if pyproject.is_file():
        tool = _table(_load(pyproject).get("tool", {}), pyproject, "tool")
        if "releasing" in tool:
            candidates.append(
                (pyproject, _table(tool["releasing"], pyproject, "tool.releasing"))
            )
    for name in STANDALONES:
        standalone = root / name
        if standalone.is_file():
            candidates.append((standalone, _load(standalone)))
    if not candidates:
        raise ConfigError(
            f"no release declaration: expected [tool.releasing] in {pyproject}, "
            f"or {' or '.join(STANDALONES)} beside it"
        )
    if len(candidates) > 1:
        declaring = " and ".join(str(path) for path, _ in candidates)
        raise ConfigError(
            f"ambiguous release declaration: {declaring} declare one; keep exactly one"
        )
    return candidates[0]


def load_release_config(root: Path) -> ReleaseConfig:
    """Load, default and validate the declaration for the project at ``root``.

    ``root`` may be a Git checkout or a plain exported tree. Every referenced
    file must exist below it. Unknown keys are rejected so a misspelled key
    cannot silently fall back to a default.
    """
    root = root.resolve()
    if not root.is_dir():
        raise ConfigError(f"project root must be a directory: {root}")
    source, raw = locate(root)
    where = f"{source.name}: "
    _reject_unknown(raw, _KEYS, where)
    ecosystem = _choice(raw, "ecosystem", ECOSYSTEMS, "python", where)
    defaults = _ECOSYSTEM_DEFAULTS[ecosystem]
    repository = _optional(raw, "repository", where)
    if repository is None:
        raise ConfigError(f"{where}repository is required, as owner/name")
    if not _REPOSITORY.fullmatch(repository):
        raise ConfigError(f"{where}repository must be owner/name: {repository!r}")
    forge = _choice(raw, "forge", FORGES, "github", where)
    index = _choice(raw, "index", INDEXES, str(defaults["index"]), where)
    default_files = [str(item) for item in _as_list(defaults["version-files"])]
    version_files = _relative_paths(raw, "version-files", default_files, where)
    if not version_files and ecosystem != "hugo-component":
        raise ConfigError(f"{where}version-files must name at least one file")
    changelog = _text(
        raw, "changelog", str(defaults.get("changelog", "CHANGELOG.md")), where
    )
    if changelog != "antsibull":
        changelog = _relative_path(
            changelog, f"{where}changelog", allow_directory=False
        )
    tag_format = _text(raw, "tag-format", "v{version}", where)
    if "{version}" not in tag_format or _formats_badly(tag_format, version="1"):
        raise ConfigError(f"{where}tag-format must contain {{version}}: {tag_format!r}")
    tag_message = _text(raw, "tag-message", "version {version}", where)
    if _formats_badly(tag_message, version="1", tag="v1"):
        raise ConfigError(
            f"{where}tag-message may only use {{version}} and {{tag}}: {tag_message!r}"
        )
    pins = tuple(
        _pin(item, f"{where}dependency-pins[{number}]")
        for number, item in enumerate(_as_list(raw.get("dependency-pins", [])))
    )
    allowed_attribution = _allowed_attribution(raw, where)
    readmes = tuple(
        _readme(item, f"{where}readmes[{number}]")
        for number, item in enumerate(_as_list(raw.get("readmes", [{}])))
    )
    if not readmes:
        raise ConfigError(f"{where}readmes must not be empty; omit it for the default")
    config = ReleaseConfig(
        root=root,
        source=source,
        repository=repository,
        forge=forge,
        index=index,
        ecosystem=ecosystem,
        version_files=version_files,
        changelog=changelog,
        tag_format=tag_format,
        tag_message=tag_message,
        dependency_pins=pins,
        allowed_attribution=allowed_attribution,
        readmes=readmes,
    )
    _check_files(config)
    return config


def _allowed_attribution(raw: Mapping[str, object], where: str) -> tuple[str, ...]:
    """The attributions this project carries on purpose.

    A project bound by a policy that requires the disclosure, such as the
    Ansible Community Policy for AI-Assisted Contributions, names what it
    allows rather than turning the check off. An entry is a rule name, or a
    rule name and a regular expression for the values it covers.
    """
    entries = []
    for value in _as_list(raw.get("allowed-attribution", [])):
        if not isinstance(value, str):
            raise ConfigError(f"{where}allowed-attribution must hold strings")
        try:
            attribution.allowance(value)
        except ValueError as exc:
            raise ConfigError(f"{where}allowed-attribution {exc}") from exc
        entries.append(value)
    return tuple(dict.fromkeys(entries))


def _check_files(config: ReleaseConfig) -> None:
    missing = [
        path
        for path in (
            *config.version_files,
            *([] if config.changelog == "antsibull" else [config.changelog]),
            *(pin.file for pin in config.dependency_pins),
            *(readme.source_path for readme in config.readmes),
            *(copy for readme in config.readmes for copy in readme.copies),
        )
        if not (config.root / path).is_file()
    ]
    if (
        config.changelog == "antsibull"
        and not (config.root / config.changelog_path).is_file()
    ):
        missing.append(config.changelog_path)
    if missing:
        raise ConfigError(
            "declared files are missing below "
            f"{config.root}: {', '.join(sorted(set(missing)))}"
        )


def _load(path: Path) -> Mapping[str, object]:
    try:
        with path.open("rb") as stream:
            return tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc


def _table(value: object, path: Path, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ConfigError(f"{path}: {name} must be a table")
    return value


def _reject_unknown(
    raw: Mapping[str, object], keys: frozenset[str], where: str
) -> None:
    unknown = sorted(set(raw) - keys)
    if unknown:
        raise ConfigError(f"{where}unknown key(s): {', '.join(unknown)}")


def _optional(raw: Mapping[str, object], key: str, where: str) -> str | None:
    """The declared value of ``key``, or None where the table does not have it."""
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{where}{key} must be a non-empty string")
    return value


def _text(raw: Mapping[str, object], key: str, default: str, where: str) -> str:
    """The declared value of ``key``, or the default this package applies."""
    value = _optional(raw, key, where)
    return default if value is None else value


def _choice(
    raw: Mapping[str, object],
    key: str,
    allowed: tuple[str, ...],
    default: str,
    where: str,
) -> str:
    value = _text(raw, key, default, where)
    if value not in allowed:
        raise ConfigError(
            f"{where}{key} must be one of {', '.join(allowed)}: {value!r}"
        )
    return value


def _bool(raw: Mapping[str, object], key: str, where: str) -> bool:
    value = raw.get(key, False)
    if not isinstance(value, bool):
        raise ConfigError(f"{where}{key} must be true or false")
    return value


def _as_list(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ConfigError("expected an array")
    return value


def _relative_path(value: object, where: str, *, allow_directory: bool = False) -> str:
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{where} must be a non-empty relative path")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or "\\" in value
        or ".." in path.parts
        or str(path) == "."
        or (value.endswith("/") and not allow_directory)
    ):
        raise ConfigError(
            f"{where} must be a relative file path inside the project: {value!r}"
        )
    return str(path)


def _relative_paths(
    raw: Mapping[str, object], key: str, default: list[str], where: str
) -> tuple[str, ...]:
    value = raw.get(key, default)
    if not isinstance(value, list):
        raise ConfigError(f"{where}{key} must be an array of relative paths")
    paths = tuple(_relative_path(item, f"{where}{key}") for item in value)
    if len(set(paths)) != len(paths):
        raise ConfigError(f"{where}{key} lists a path twice")
    return paths


def _pin(item: object, where: str) -> DependencyPin:
    if not isinstance(item, Mapping):
        raise ConfigError(f"{where} must be a table with file and name")
    _reject_unknown(item, _PIN_KEYS, f"{where}: ")
    file = _relative_path(item.get("file"), f"{where}.file")
    name = _optional(item, "name", f"{where}.")
    if name is None or not re.fullmatch(
        r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?", name
    ):
        raise ConfigError(f"{where}.name must be a package name")
    return DependencyPin(file=file, name=name)


def _readme(item: object, where: str) -> ReadmeConfig:
    if not isinstance(item, Mapping):
        raise ConfigError(f"{where} must be a table")
    _reject_unknown(item, _README_KEYS, f"{where}: ")
    ref = _text(item, "ref", "refs/tags/{tag}", f"{where}.")
    if _formats_badly(ref, version="1", tag="v1"):
        raise ConfigError(f"{where}.ref may only use {{version}} and {{tag}}: {ref!r}")
    return ReadmeConfig(
        source_path=_relative_path(
            item.get("source-path", "README.md"), f"{where}.source-path"
        ),
        ref=ref,
        simplify_badges=_bool(item, "simplify-badges", f"{where}."),
        collapse_header=_bool(item, "collapse-header", f"{where}."),
        copies=_relative_paths(item, "copies", [], f"{where}."),
    )


def _formats_badly(template: str, **fields: str) -> bool:
    try:
        template.format(**fields)
    except (KeyError, IndexError, ValueError):
        return True
    return False
