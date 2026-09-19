# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later

from pathlib import Path

import pytest

from releasing.config import load_release_config
from releasing.version import (
    Site,
    VersionError,
    bump,
    check,
    find_sites,
    is_version,
    locked_versions,
)

PYPROJECT = '[project]\nname = "example"\nversion = "1.2.3"\n'
INIT = '"""Example."""\n\n__version__ = "1.2.3"\n'
LOCK = (
    'version = 1\n\n[[package]]\nname = "example"\nversion = "1.2.3"\n'
    'source = { editable = "." }\n'
)
DATA = '{\n  "productVersion": "1.2.3",\n  "x": 1\n}\n'
GUI = (
    "[project]\r\nname = 'gui'\r\nversion = '1.2.3'\r\n"
    "dependencies = ['example >= 1.2.3 , <2']\r\n"
)


def project(
    tmp_path: Path, declaration: str = "", files: dict[str, str] | None = None
) -> Path:
    (tmp_path / "README.md").write_text("# Example\n", encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        PYPROJECT
        + '\n[tool.releasing]\nrepository = "foundata/example"\n'
        + declaration,
        encoding="utf-8",
    )
    for name, content in (files or {}).items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="")
    return tmp_path


@pytest.mark.parametrize(
    "value", ["1.0.0", "10.20.30", "1.0.0rc1", "1.0.0.dev0", "1.0.0-rc.1", "2.0.0a1"]
)
def test_accepted_versions(value: str) -> None:
    assert is_version(value)


@pytest.mark.parametrize("value", ["1.0", "v1.0.0", "1.0.0.0", "latest", "1.0.0 "])
def test_rejected_versions(value: str) -> None:
    assert not is_version(value)


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ('version = "1.2.3"', "1.2.3"),
        ("version = '1.2.3'", "1.2.3"),
        ('__version__ = "1.2.3"', "1.2.3"),
        ('VERSION = "1.2.3"', "1.2.3"),
        ('  "productVersion": "1.2.3",', "1.2.3"),
        ('version: "1.2.3"', "1.2.3"),
        ("version: 1.2.3", "1.2.3"),
        ("version = 1.2.3   ", "1.2.3"),
    ],
)
def test_site_spellings(tmp_path: Path, line: str, expected: str) -> None:
    root = project(
        tmp_path,
        'version-files = ["SITE"]\n',
        {"SITE": f"# heading\n{line}\ntrailer\n"},
    )
    assert find_sites(root, load_release_config(root)) == [Site("SITE", 2, expected)]


@pytest.mark.parametrize(
    "content",
    [
        "no version here\n",
        'version = "1.2.3"\nversion = "1.2.3"\n',
        'version = "1.2.3" # comment\n',
        'version = "one.two.three"\n',
        'the version = "1.2.3"\n',
    ],
)
def test_files_without_exactly_one_site_are_errors(
    tmp_path: Path, content: str
) -> None:
    root = project(tmp_path, 'version-files = ["SITE"]\n', {"SITE": content})
    with pytest.raises(VersionError, match="expected exactly one version line"):
        find_sites(root, load_release_config(root))


def test_check_returns_the_agreed_version(tmp_path: Path) -> None:
    root = project(
        tmp_path,
        'version-files = ["pyproject.toml", "src/example/__init__.py"]\n',
        {"src/example/__init__.py": INIT, "uv.lock": LOCK},
    )
    config = load_release_config(root)
    assert check(root, config) == "1.2.3"
    assert check(root, config, expect="1.2.3") == "1.2.3"
    assert check(root, config, tags_on_head=["v1.2.3", "x"]) == "1.2.3"


def test_check_reports_every_disagreement(tmp_path: Path) -> None:
    root = project(
        tmp_path,
        'version-files = ["pyproject.toml", "src/example/__init__.py"]\n',
        {"src/example/__init__.py": INIT.replace("1.2.3", "1.2.4")},
    )
    with pytest.raises(VersionError) as excinfo:
        check(root, load_release_config(root))
    message = str(excinfo.value)
    assert "version sites disagree" in message
    assert "pyproject.toml:3: 1.2.3" in message
    assert "src/example/__init__.py:3: 1.2.4" in message


def test_check_compares_expectation_lockfile_and_tag(tmp_path: Path) -> None:
    root = project(tmp_path, files={"uv.lock": LOCK.replace("1.2.3", "1.2.2")})
    with pytest.raises(VersionError) as excinfo:
        check(root, load_release_config(root), expect="9.9.9", tags_on_head=["v1.0.0"])
    message = str(excinfo.value)
    assert "expected 9.9.9, sites state 1.2.3" in message
    assert "uv.lock records example 1.2.2" in message
    assert "tag v1.2.3 does not point at the current revision" in message
    assert locked_versions(root) == {"example": "1.2.2"}
    assert locked_versions(tmp_path / "nowhere") == {}


def test_check_verifies_lockstep_pin_bound(tmp_path: Path) -> None:
    root = project(
        tmp_path,
        'dependency-pins = [{ file = "gui/pyproject.toml", name = "example" }]\n',
        {"gui/pyproject.toml": 'dependencies = ["example>=1.2.2,<2"]\n'},
    )
    with pytest.raises(VersionError, match=r"lower bound is 1\.2\.2, expected 1\.2\.3"):
        check(root, load_release_config(root))


def test_bump_rewrites_sites_and_pins_preserving_layout(tmp_path: Path) -> None:
    root = project(
        tmp_path,
        'version-files = ["pyproject.toml", "src/example/__init__.py", '
        '"gui/pyproject.toml", "data.json"]\n'
        'dependency-pins = [{ file = "gui/pyproject.toml", name = "example" }]\n',
        {"src/example/__init__.py": INIT, "gui/pyproject.toml": GUI, "data.json": DATA},
    )
    edits = bump(root, load_release_config(root), "2.0.0")
    assert sorted(edit.file for edit in edits) == [
        "data.json",
        "gui/pyproject.toml",
        "pyproject.toml",
        "src/example/__init__.py",
    ]
    assert (root / "gui" / "pyproject.toml").read_bytes() == (
        b"[project]\r\nname = 'gui'\r\nversion = '2.0.0'\r\n"
        b"dependencies = ['example >= 2.0.0 , <2']\r\n"
    )
    assert (root / "data.json").read_text(encoding="utf-8") == DATA.replace(
        "1.2.3", "2.0.0"
    )
    assert (root / "src" / "example" / "__init__.py").read_text(
        encoding="utf-8"
    ) == INIT.replace("1.2.3", "2.0.0")
    assert check(root, load_release_config(root)) == "2.0.0"


def test_bump_refuses_bad_or_unchanged_versions_without_writing(tmp_path: Path) -> None:
    root = project(tmp_path)
    with pytest.raises(VersionError, match="not a version"):
        bump(root, load_release_config(root), "two")
    with pytest.raises(VersionError, match=r"already state 1\.2\.3"):
        bump(root, load_release_config(root), "1.2.3")
    assert (root / "pyproject.toml").read_text(encoding="utf-8").startswith(PYPROJECT)
