# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later

from pathlib import Path

import pytest

from releasing.config import (
    ConfigError,
    DependencyPin,
    ReadmeConfig,
    load_release_config,
)


def project(tmp_path: Path, declaration: str, *, standalone: bool = False) -> Path:
    (tmp_path / "README.md").write_text("# Example\n", encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")
    if standalone:
        (tmp_path / "releasing.toml").write_text(declaration, encoding="utf-8")
    else:
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "example"\nversion = "1.0.0"\n\n[tool.releasing]\n'
            + declaration,
            encoding="utf-8",
        )
    return tmp_path


def test_the_changelog_path_names_the_file_whichever_format_owns_it(
    tmp_path: Path,
) -> None:
    # antsibull-changelog owns a directory of its own, and a report that says
    # "antsibull" instead of the file leaves the reader looking for it.
    (tmp_path / "README.md").write_text("# x\n", encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")
    (tmp_path / "galaxy.yml").write_text('version: "1.0.0"\n', encoding="utf-8")
    (tmp_path / "changelogs").mkdir()
    (tmp_path / "changelogs" / "changelog.yaml").write_text(
        "releases:\n", encoding="utf-8"
    )
    (tmp_path / "releasing.toml").write_text(
        'repository = "foundata/example"\nversion-files = ["galaxy.yml"]\n',
        encoding="utf-8",
    )

    keep_a_changelog = load_release_config(tmp_path)
    assert keep_a_changelog.changelog_path == "CHANGELOG.md"

    (tmp_path / "releasing.toml").write_text(
        'repository = "foundata/example"\necosystem = "ansible-collection"\n',
        encoding="utf-8",
    )
    collection = load_release_config(tmp_path)
    assert collection.changelog_path == "changelogs/changelog.yaml"


def test_minimal_declaration_applies_every_default(tmp_path: Path) -> None:
    config = load_release_config(project(tmp_path, 'repository = "foundata/example"\n'))
    assert config.source == tmp_path.resolve() / "pyproject.toml"
    assert (config.owner, config.name) == ("foundata", "example")
    assert (config.forge, config.index, config.ecosystem) == (
        "github",
        "pypi",
        "python",
    )
    assert config.version_files == ("pyproject.toml",)
    assert config.changelog == "CHANGELOG.md"
    assert config.changelog_format == "keep-a-changelog"
    assert config.tag("1.2.3") == "v1.2.3"
    assert config.tag_message_for("1.2.3") == "version 1.2.3"
    assert config.readmes == (ReadmeConfig(),)
    assert config.dependency_pins == ()


def test_standalone_file_uses_the_same_keys(tmp_path: Path) -> None:
    (tmp_path / "VERSION").write_text("1.0.0\n", encoding="utf-8")
    config = load_release_config(
        project(
            tmp_path,
            'repository = "foundata/example"\nversion-files = ["VERSION"]\n',
            standalone=True,
        )
    )
    assert config.source.name == "releasing.toml"
    assert config.version_files == ("VERSION",)


def test_full_declaration_round_trips(tmp_path: Path) -> None:
    root = project(
        tmp_path,
        """repository = "foundata/product"
forge = "github"
index = "pypi"
ecosystem = "python"
version-files = ["pyproject.toml", "packages/gui/pyproject.toml"]
changelog = "CHANGELOG.md"
tag-format = "release-{version}"
tag-message = "{tag}: version {version}"
dependency-pins = [{ file = "packages/gui/pyproject.toml", name = "product" }]

[[tool.releasing.readmes]]
source-path = "README.md"
ref = "refs/heads/main"
simplify-badges = true
collapse-header = true
copies = ["packages/gui/README.md"]
""",
    )
    (root / "packages" / "gui").mkdir(parents=True)
    (root / "packages" / "gui" / "pyproject.toml").write_text("", encoding="utf-8")
    (root / "packages" / "gui" / "README.md").write_text("", encoding="utf-8")
    config = load_release_config(root)
    assert config.version_files == ("pyproject.toml", "packages/gui/pyproject.toml")
    assert config.tag("2.0.0") == "release-2.0.0"
    assert config.tag_message_for("2.0.0") == "release-2.0.0: version 2.0.0"
    assert config.dependency_pins == (
        DependencyPin(file="packages/gui/pyproject.toml", name="product"),
    )
    assert config.readmes == (
        ReadmeConfig(
            source_path="README.md",
            ref="refs/heads/main",
            simplify_badges=True,
            collapse_header=True,
            copies=("packages/gui/README.md",),
        ),
    )


def test_ecosystem_defaults_for_collections_and_hugo(tmp_path: Path) -> None:
    root = project(
        tmp_path,
        'repository = "foundata/ansible-collection-example"\n'
        'ecosystem = "ansible-collection"\n',
        standalone=True,
    )
    (root / "galaxy.yml").write_text("version: 1.0.0\n", encoding="utf-8")
    (root / "changelogs").mkdir()
    (root / "changelogs" / "changelog.yaml").write_text(
        "releases: {}\n", encoding="utf-8"
    )
    config = load_release_config(root)
    assert (config.index, config.version_files) == ("galaxy", ("galaxy.yml",))
    assert (config.changelog, config.changelog_format) == ("antsibull", "antsibull")

    (tmp_path / "hugo").mkdir()
    hugo = project(
        tmp_path / "hugo",
        'repository = "foundata/hugo-component-example"\n'
        'ecosystem = "hugo-component"\n',
        standalone=True,
    )
    config = load_release_config(hugo)
    assert (config.index, config.version_files) == ("none", ())


@pytest.mark.parametrize(
    ("declaration", "message"),
    [
        ("", "repository is required"),
        ('repository = "example"\n', "owner/name"),
        ('repository = "foundata/example"\nrepositroy = "x"\n', "unknown key"),
        ('repository = "foundata/example"\nforge = "svn"\n', "forge must be one of"),
        ('repository = "foundata/example"\nindex = "npm"\n', "index must be one of"),
        ('repository = "foundata/example"\necosystem = "go"\n', "ecosystem must be"),
        ('repository = "foundata/example"\nversion-files = []\n', "at least one file"),
        (
            'repository = "foundata/example"\nversion-files = ["../x"]\n',
            "inside the project",
        ),
        (
            'repository = "foundata/example"\nversion-files = ["/etc/x"]\n',
            "inside the project",
        ),
        ('repository = "foundata/example"\nversion-files = ["a", "a"]\n', "twice"),
        ('repository = "foundata/example"\ntag-format = "release"\n', "{version}"),
        ('repository = "foundata/example"\ntag-format = "v{versoin}"\n', "{version}"),
        ('repository = "foundata/example"\ntag-message = "{author}"\n', "{tag}"),
        ('repository = "foundata/example"\nreadmes = []\n', "must not be empty"),
        (
            'repository = "foundata/example"\nreadmes = [{ source-path = "README.md", simplify = true }]\n',
            "unknown key",
        ),
        (
            'repository = "foundata/example"\nreadmes = [{ ref = "{branch}" }]\n',
            "{tag}",
        ),
        (
            'repository = "foundata/example"\ndependency-pins = [{ file = "pyproject.toml" }]\n',
            "package name",
        ),
        (
            'repository = "foundata/example"\nversion-files = ["missing.py"]\n',
            "missing.py",
        ),
        ('repository = "foundata/example"\nchangelog = "HISTORY.md"\n', "HISTORY.md"),
    ],
)
def test_invalid_declarations_are_rejected_with_a_reason(
    tmp_path: Path, declaration: str, message: str
) -> None:
    with pytest.raises(ConfigError, match=message):
        load_release_config(project(tmp_path, declaration))


def test_missing_and_ambiguous_declarations(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\n', encoding="utf-8"
    )
    with pytest.raises(ConfigError, match="no release declaration"):
        load_release_config(tmp_path)
    project(tmp_path, 'repository = "foundata/example"\n')
    (tmp_path / "releasing.toml").write_text(
        'repository = "foundata/example"\n', encoding="utf-8"
    )
    with pytest.raises(ConfigError, match="ambiguous"):
        load_release_config(tmp_path)


def test_unreadable_toml_and_missing_root(tmp_path: Path) -> None:
    (tmp_path / "releasing.toml").write_text("repository = \n", encoding="utf-8")
    with pytest.raises(ConfigError, match="cannot read"):
        load_release_config(tmp_path)
    with pytest.raises(ConfigError, match="must be a directory"):
        load_release_config(tmp_path / "absent")
