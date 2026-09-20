# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later

from pathlib import Path

import pytest

from releasing import antsibull

CHANGES = """---
ancestor: null
releases:
  1.4.0:
    changes:
      release_summary: 'Release Date: 2026-08-28


        Maintenance release.

        '
      minor_changes:
        - '``sysctl`` - give every loop a private variable instead of ``item``.'
        - 'A second entry.'
      bugfixes:
        - 'A bug that was fixed.'
      trivial:
        - 'Not published anywhere.'
    fragments:
      - 1.4.0-release.yaml
    release_date: '2026-08-28'
  1.3.0:
    changes:
      bugfixes:
        - 'An older fix.'
    release_date: '2026-08-13'
"""
CONFIG = """---
prelude_section_name: "release_summary"
prelude_section_title: "Release Summary"
sections:
  - ["major_changes", "Major Changes"]
  - ["minor_changes", "Minor Changes"]
  - ["bugfixes", "Bugfixes"]
title: "foundata.example Ansible collection"
"""


@pytest.fixture
def collection(tmp_path: Path) -> Path:
    (tmp_path / "changelogs").mkdir()
    (tmp_path / "changelogs" / "changelog.yaml").write_text(CHANGES, encoding="utf-8")
    (tmp_path / "changelogs" / "config.yaml").write_text(CONFIG, encoding="utf-8")
    return tmp_path


def test_notes_render_the_recorded_changes_in_the_declared_order(
    collection: Path,
) -> None:
    assert antsibull.notes(collection, "1.4.0") == (
        "### Release Summary\n"
        "\n"
        "Release Date: 2026-08-28\n"
        "\n"
        "Maintenance release.\n"
        "\n"
        "### Minor Changes\n"
        "\n"
        "- `sysctl` - give every loop a private variable instead of `item`.\n"
        "- A second entry.\n"
        "\n"
        "### Bugfixes\n"
        "\n"
        "- A bug that was fixed.\n"
    )


def test_a_section_the_project_does_not_declare_is_not_rendered(
    collection: Path,
) -> None:
    # "trivial" is recorded but belongs in no published section.
    assert "Not published anywhere" not in antsibull.notes(collection, "1.4.0")


def test_titles_fall_back_to_the_tool_defaults(collection: Path) -> None:
    (collection / "changelogs" / "config.yaml").unlink()
    rendered = antsibull.notes(collection, "1.4.0")
    assert "### Release Summary" in rendered
    assert "### Minor Changes" in rendered
    prelude, sections = antsibull.section_titles(collection)
    assert prelude == antsibull.DEFAULT_PRELUDE_TITLE
    assert sections == antsibull.DEFAULT_SECTIONS


def test_new_modules_and_plugins_are_listed(collection: Path) -> None:
    (collection / "changelogs" / "changelog.yaml").write_text(
        """---
releases:
  1.4.0:
    changes:
      minor_changes:
        - 'An entry.'
    modules:
      - name: example_module
        description: Does the thing.
        namespace: ''
    plugins:
      lookup:
        - name: example_lookup
          description: Looks the thing up.
    release_date: '2026-08-28'
""",
        encoding="utf-8",
    )
    rendered = antsibull.notes(collection, "1.4.0")
    assert "### New Modules\n\n- example_module - Does the thing." in rendered
    assert (
        "### New Lookup Plugins\n\n- example_lookup - Looks the thing up." in rendered
    )


def test_an_unknown_version_is_refused(collection: Path) -> None:
    with pytest.raises(antsibull.AntsibullError, match=r"no release 9\.9\.9"):
        antsibull.notes(collection, "9.9.9")


def test_a_release_without_changes_is_refused(collection: Path) -> None:
    (collection / "changelogs" / "changelog.yaml").write_text(
        "releases:\n  1.0.0:\n    release_date: '2026-01-01'\n", encoding="utf-8"
    )
    with pytest.raises(antsibull.AntsibullError, match="records no changes"):
        antsibull.notes(collection, "1.0.0")


def test_malformed_data_is_reported_rather_than_raised_raw(collection: Path) -> None:
    (collection / "changelogs" / "changelog.yaml").write_text(
        "releases: [not, a, mapping]\n", encoding="utf-8"
    )
    with pytest.raises(antsibull.AntsibullError, match="releases mapping"):
        antsibull.notes(collection, "1.4.0")
    (collection / "changelogs" / "changelog.yaml").write_text(
        "releases:\n  1.4.0: 'a string'\n", encoding="utf-8"
    )
    with pytest.raises(antsibull.AntsibullError, match="is not a mapping"):
        antsibull.notes(collection, "1.4.0")
    (collection / "changelogs" / "changelog.yaml").write_text(
        "releases:\n  - [\n", encoding="utf-8"
    )
    with pytest.raises(antsibull.AntsibullError, match="not valid YAML"):
        antsibull.notes(collection, "1.4.0")


def test_a_missing_file_is_reported_with_its_path(tmp_path: Path) -> None:
    with pytest.raises(antsibull.AntsibullError, match=r"changelog\.yaml"):
        antsibull.notes(tmp_path, "1.0.0")
