# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later

import os
from pathlib import Path

import pytest

from tests.support import FIXTURES, POSIX_ONLY, TRANSFORMER, prepare

pytestmark = pytest.mark.integration


def make_file(root: Path, relative: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("fixture\n", encoding="utf-8")
    return path


def test_mixed_content_checks_only_active_targets(tmp_path: Path) -> None:
    source = (FIXTURES / "mixed-content.md").read_text(encoding="utf-8")
    for relative in (
        "docs/guide.md",
        "docs/a(b).md",
        "assets/logo.svg",
        "assets/shot.avif",
    ):
        make_file(tmp_path, relative)
    TRANSFORMER.validate_local_files(source, repo_root=tmp_path)
    assert not (tmp_path / "untouched.md").exists()
    assert not (tmp_path / "untouched.svg").exists()


def test_source_path_encoding_queries_and_directory_targets(tmp_path: Path) -> None:
    for relative in (
        "docs/README.md",
        "docs/a b.md",
        "docs/a%20b.md",
        "docs/caf\u00e9.md",
        "LICENSES/GPL.txt",
    ):
        make_file(tmp_path, relative)
    source = (
        "[space](./a%20b.md?download=1#missing-anchor) [literal](a%2520b.md)\n"
        "[unicode](caf%C3%A9.md) [license](../LICENSES/GPL.txt)\n"
        "[self](?plain=1) [directory](../LICENSES/) [root](../)\n"
        '<a href="./a%20b.md?x=1&amp;y=2#part">HTML</a>\n'
    )
    TRANSFORMER.validate_local_files(
        source, repo_root=tmp_path, source_path="docs/README.md"
    )


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_missing_targets_report_all_original_locations(
    tmp_path: Path, newline: str
) -> None:
    source = newline.join(["# Title", "", "[one](missing.md)", "![two](missing.svg)"])
    with pytest.raises(ValueError) as raised:
        TRANSFORMER.validate_local_files(source, repo_root=tmp_path)
    assert str(raised.value).splitlines() == [
        "3:7: 'missing.md': local target does not exist",
        "4:8: 'missing.svg': local target does not exist",
    ]


@pytest.mark.parametrize(
    "source",
    [
        "[unused]: missing.md\n",
        "![ref][logo]\n\n[logo]: missing.svg\n",
        '<video poster="missing.png"></video>',
    ],
)
def test_references_and_resource_attributes_are_checked(
    tmp_path: Path, source: str
) -> None:
    with pytest.raises(ValueError, match="local target does not exist"):
        TRANSFORMER.validate_local_files(source, repo_root=tmp_path)


def test_nonlocal_and_protected_destinations_need_no_local_files(
    tmp_path: Path,
) -> None:
    source = (
        "[external](https://example.org/no-such-file) ![cdn](//example.org/img.png)\n"
        "[anchor](#missing) [mail](mailto:docs@example.org) [empty]()\n\n"
        "`[inline](missing.md)` <!-- <img src='missing.svg'> -->\n\n"
        "```markdown\n[x](missing.md)\n```\n\n"
        "    [indented](missing.md)\n"
    )
    TRANSFORMER.validate_local_files(source, repo_root=tmp_path)


@pytest.mark.parametrize("relative", ["/root.md", "../outside.md", "%2e%2e/outside.md"])
def test_unresolvable_destinations_fail_local_check(
    tmp_path: Path, relative: str
) -> None:
    with pytest.raises(ValueError, match=r"root-relative|escapes the repository root"):
        TRANSFORMER.validate_local_files(f"[x]({relative})", repo_root=tmp_path)


@pytest.mark.parametrize("relative", ["a%00.md", "a%0A.md", "a%5Cb.md"])
def test_encoded_control_characters_and_backslashes_are_refused(
    tmp_path: Path, relative: str
) -> None:
    source = f"[x]({relative})"
    with pytest.raises(ValueError, match="control character or backslash"):
        TRANSFORMER.validate_local_files(source, repo_root=tmp_path)
    with pytest.raises(ValueError, match="control character or backslash"):
        prepare(source)
    assert prepare(source, strict=False) == source


@POSIX_ONLY
def test_internal_symlinks_are_accepted(tmp_path: Path) -> None:
    make_file(tmp_path, "docs/guide.md")
    (tmp_path / "guide.md").symlink_to("docs/guide.md")
    (tmp_path / "alias").symlink_to("docs", target_is_directory=True)
    TRANSFORMER.validate_local_files(
        "[guide](guide.md) [alias](alias/guide.md)", repo_root=tmp_path
    )


@pytest.mark.parametrize("kind", ["outside", "broken", "loop"])
@POSIX_ONLY
def test_invalid_symlinks_are_refused(tmp_path: Path, kind: str) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    make_file(tmp_path, "outside.md")
    target = {"outside": "../outside.md", "broken": "absent.md", "loop": "link.md"}[
        kind
    ]
    (root / "link.md").symlink_to(target)
    with pytest.raises(ValueError) as raised:
        TRANSFORMER.validate_local_files("[link](link.md)", repo_root=root)
    assert "1:8: 'link.md':" in str(raised.value)
    if kind == "outside":
        assert "outside the repository root" in str(raised.value)
    if kind == "broken":
        assert "does not exist" in str(raised.value)


@POSIX_ONLY
def test_root_may_be_a_symlink_to_a_directory(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    make_file(root, "guide.md")
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)
    TRANSFORMER.validate_local_files("[guide](guide.md)", repo_root=alias)


@pytest.mark.parametrize("kind", ["missing", "file"])
def test_invalid_root_fails_even_without_links(tmp_path: Path, kind: str) -> None:
    root = tmp_path / "invalid"
    if kind == "file":
        root.touch()
    with pytest.raises(ValueError, match="repository root"):
        TRANSFORMER.validate_local_files("Plain text", repo_root=root)


def test_images_must_be_files_and_trailing_slashes_must_name_directories(
    tmp_path: Path,
) -> None:
    make_file(tmp_path, "docs/guide.md")
    with pytest.raises(ValueError, match="image target must be a regular file"):
        TRANSFORMER.validate_local_files("![image](docs/)", repo_root=tmp_path)
    with pytest.raises(ValueError, match="trailing slash must be a directory"):
        TRANSFORMER.validate_local_files("[guide](docs/guide.md/)", repo_root=tmp_path)


@POSIX_ONLY
def test_special_files_are_refused_without_opening_them(tmp_path: Path) -> None:
    os.mkfifo(tmp_path / "pipe")
    with pytest.raises(ValueError, match="regular file or directory"):
        TRANSFORMER.validate_local_files("[pipe](pipe)", repo_root=tmp_path)
