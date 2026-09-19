# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later

from datetime import date

import pytest

from releasing.changelog import (
    ChangelogError,
    antsibull_has_release,
    check,
    parse,
    release,
    show,
)
from releasing.forges import Forge

FORGE = Forge(
    "github",
    "foundata/example",
    "https://github.com",
    "https://raw.githubusercontent.com",
    "https://api.github.com",
)
HEAD = """# Changelog

All notable changes to this project will be documented in this file.


## [Unreleased]

{unreleased}


## [1.2.0] - 2026-08-27

### Added

- A feature with a `## [9.9.9]` code span.

```text
## [0.0.0] - inside a fence, ignored
```


## [1.1.0] - 2026-08-20

### Fixed

- A bug.


[unreleased]: https://github.com/foundata/example/compare/v1.2.0...HEAD
[1.2.0]: https://github.com/foundata/example/releases/tag/v1.2.0
[1.1.0]: https://github.com/foundata/example/releases/tag/v1.1.0
"""
EMPTY = HEAD.format(unreleased="- Nothing worth mentioning right now.")
PENDING = HEAD.format(unreleased="### Changed\n\n- Something.")


def test_parse_finds_sections_definitions_and_ignores_fences() -> None:
    changelog = parse(PENDING)
    assert [section.label for section in changelog.sections] == [
        "Unreleased",
        "1.2.0",
        "1.1.0",
    ]
    assert changelog.sections[1].date == "2026-08-27"
    assert set(changelog.definitions) == {"unreleased", "1.2.0", "1.1.0"}
    assert changelog.sections[2].text == "### Fixed\n\n- A bug.\n"


def test_show_returns_one_section_body() -> None:
    assert show(PENDING, "1.1.0") == "### Fixed\n\n- A bug.\n"
    assert show(PENDING, "unreleased") == "### Changed\n\n- Something.\n"
    with pytest.raises(ChangelogError, match="no changelog section"):
        show(PENDING, "3.0.0")


def test_check_accepts_the_convention_and_the_latest_version() -> None:
    assert check(EMPTY, forge=FORGE, tag_format="v{version}") == []
    assert check(EMPTY, forge=FORGE, tag_format="v{version}", version="1.2.0") == []
    assert check(EMPTY, forge=FORGE, tag_format="v{version}", version="1.3.0") == [
        "the latest released section must be [1.3.0]"
    ]


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        (
            ("## [Unreleased]\n", "## [Pending]\n"),
            "first section must be ## [Unreleased]",
        ),
        (("## [1.2.0] - 2026-08-27", "## [1.2.0]"), "needs a release date"),
        (
            ("## [1.2.0] - 2026-08-27", "## [1.2.0] - 2026-13-01"),
            "needs a release date",
        ),
        (("## [1.1.0] - 2026-08-20", "## [1.2.0] - 2026-08-20"), "duplicate section"),
        (("## [1.1.0] - 2026-08-20", "## [1.3.0] - 2026-08-20"), "newest first"),
        (("## [1.1.0] - 2026-08-20", "## [one] - 2026-08-20"), "not a version"),
        (
            ("[1.1.0]: https://github.com/foundata/example/releases/tag/v1.1.0\n", ""),
            "no link definition [1.1.0]",
        ),
        (
            ("compare/v1.2.0...HEAD", "compare/v1.1.0...HEAD"),
            "must compare v1.2.0...HEAD",
        ),
        (
            (
                "[unreleased]: https://github.com/foundata/example/compare/v1.2.0...HEAD\n",
                "",
            ),
            "missing link definition [unreleased]",
        ),
    ],
)
def test_check_names_each_problem(mutation: tuple[str, str], expected: str) -> None:
    problems = check(EMPTY.replace(*mutation), forge=FORGE, tag_format="v{version}")
    assert any(expected in problem for problem in problems), problems


def test_release_moves_unreleased_into_a_dated_section_with_links() -> None:
    result = release(
        PENDING, "1.3.0", forge=FORGE, tag_format="v{version}", when=date(2026, 9, 20)
    )
    assert result == HEAD.format(
        unreleased="- Nothing worth mentioning right now.\n\n\n## [1.3.0] - 2026-09-20\n\n### Changed\n\n- Something."
    ).replace(
        "[unreleased]: https://github.com/foundata/example/compare/v1.2.0...HEAD\n",
        "[unreleased]: https://github.com/foundata/example/compare/v1.3.0...HEAD\n"
        "[1.3.0]: https://github.com/foundata/example/releases/tag/v1.3.0\n",
    )
    assert check(result, forge=FORGE, tag_format="v{version}", version="1.3.0") == []
    assert show(result, "1.3.0") == "### Changed\n\n- Something.\n"


def test_release_adds_link_definitions_to_a_file_without_them() -> None:
    text = "# Changelog\n\n## [Unreleased]\n\n- First entry.\n"
    result = release(
        text, "1.0.0", forge=FORGE, tag_format="v{version}", when=date(2026, 1, 2)
    )
    assert result == (
        "# Changelog\n\n## [Unreleased]\n\n- Nothing worth mentioning right now.\n\n\n"
        "## [1.0.0] - 2026-01-02\n\n- First entry.\n\n"
        "[unreleased]: https://github.com/foundata/example/compare/v1.0.0...HEAD\n"
        "[1.0.0]: https://github.com/foundata/example/releases/tag/v1.0.0\n"
    )


def test_release_preserves_crlf_and_custom_placeholder() -> None:
    text = "# Changelog\r\n\r\n## [Unreleased]\r\n\r\n- Entry.\r\n"
    result = release(
        text,
        "1.0.0",
        forge=FORGE,
        tag_format="v{version}",
        when=date(2026, 1, 2),
        placeholder="No unreleased changes.",
    )
    assert (
        "\r\n## [Unreleased]\r\n\r\nNo unreleased changes.\r\n\r\n\r\n## [1.0.0] - 2026-01-02\r\n"
        in result
    )
    assert "\n" not in result.replace("\r\n", "")


@pytest.mark.parametrize(
    ("text", "version", "message"),
    [
        (EMPTY, "1.3.0", "nothing to release"),
        (HEAD.format(unreleased=""), "1.3.0", "nothing to release"),
        (PENDING, "1.2.0", "already exists"),
        (PENDING, "1.1.5", "not newer than the latest release 1.2.0"),
        (PENDING, "next", "not a version"),
        (PENDING.replace("compare/v1.2.0", "compare/v1.0.0"), "1.3.0", "must compare"),
    ],
)
def test_release_refuses_impossible_requests(
    text: str, version: str, message: str
) -> None:
    with pytest.raises(ChangelogError, match=message):
        release(text, version, forge=FORGE, tag_format="v{version}")


def test_antsibull_release_lookup() -> None:
    yaml = "ancestor: null\nreleases:\n  1.4.0:\n    changes: {}\n  1.3.0:\n    changes: {}\n"
    assert antsibull_has_release(yaml, "1.4.0")
    assert not antsibull_has_release(yaml, "1.4")
    assert not antsibull_has_release(yaml, "1.5.0")
