# SPDX-FileCopyrightText: foundata GmbH <https://foundata.com>
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from tests.support import POSIX_ONLY

pytestmark = pytest.mark.integration
SOURCE = b'## Rules<a id="rules"></a>\r\n\r\n- You MUST validate.\r\n'
LABELED = SOURCE[:-2] + b' `IG0001`<a id="ig0001"></a>\r\n'


def invoke(cwd: Path, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [
            sys.executable,
            "-I",
            "-m",
            "releasing",
            "markdown",
            "requirements",
            *arguments,
        ],
        cwd=cwd,
        env={**os.environ, "PATH": str(cwd / "no-programs")},
        capture_output=True,
        check=False,
        timeout=15,
    )


def snapshot(path: Path) -> tuple[bytes, int, int, int]:
    metadata = path.stat()
    return path.read_bytes(), metadata.st_ino, metadata.st_mode, metadata.st_mtime_ns


@pytest.fixture
def guide(tmp_path: Path) -> Path:
    path = tmp_path / "guide.md"
    path.write_bytes(SOURCE)
    return path


def test_check_and_export_refuse_missing_ids_without_output(guide: Path) -> None:
    before = snapshot(guide)
    for operation in ("check", "list"):
        result = invoke(guide.parent, operation, "--prefix", "IG", str(guide))
        assert result.returncode == 1
        assert result.stdout == b""
        assert b"guide.md:3: normative list item has no identifier" in result.stderr
        assert snapshot(guide) == before


def test_assign_then_check_and_export_with_no_external_programs(guide: Path) -> None:
    result = invoke(guide.parent, "assign", "--prefix", "IG", str(guide))
    assert result.returncode == 0, result.stderr
    assert result.stdout == b""
    assert b"--- " in result.stderr
    assert guide.read_bytes() == LABELED
    before = snapshot(guide)
    check = invoke(guide.parent, "check", "--prefix", "IG", str(guide))
    assert check.returncode == 0, check.stderr
    assert check.stdout == b"guide.md: 1 requirement identifier(s), 0 retired\n"
    assert check.stderr == b""
    listing = invoke(guide.parent, "list", "--prefix", "IG", str(guide))
    assert listing.returncode == 0, listing.stderr
    assert listing.stderr == b""
    assert json.loads(listing.stdout) == {
        "guide": "guide.md",
        "requirements": [
            {
                "id": "IG0001",
                "modality": "MUST",
                "section": "Rules",
                "anchor": "rules",
                "line": 3,
                "text": "You MUST validate.",
            }
        ],
        "retired": [],
    }
    assert snapshot(guide) == before


def test_dry_run_changes_no_bytes_or_metadata(guide: Path) -> None:
    before = snapshot(guide)
    result = invoke(guide.parent, "assign", "--dry-run", "--prefix", "IG", str(guide))
    assert result.returncode == 0, result.stderr
    assert result.stdout == b""
    assert b"+- You MUST validate. `IG0001`" in result.stderr
    assert snapshot(guide) == before
    assert list(guide.parent.iterdir()) == [guide]


@pytest.mark.parametrize("options", [[], ["--dry-run"]])
def test_assignment_is_noop_for_labeled_guide(guide: Path, options: list[str]) -> None:
    guide.write_bytes(LABELED)
    before = snapshot(guide)
    result = invoke(guide.parent, "assign", *options, "--prefix", "IG", str(guide))
    assert result.returncode == 0, result.stderr
    assert result.stdout == b""
    assert b"unchanged" in result.stderr
    assert snapshot(guide) == before


@pytest.mark.parametrize("options", [[], ["--dry-run"]])
@pytest.mark.parametrize("source", [SOURCE, LABELED])
def test_quiet_suppresses_assignment_diagnostics(
    guide: Path, source: bytes, options: list[str]
) -> None:
    guide.write_bytes(source)
    result = invoke(
        guide.parent, "assign", "--quiet", *options, "--prefix", "IG", str(guide)
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == result.stderr == b""


@pytest.mark.parametrize("options", [[], ["--dry-run"]])
def test_existing_errors_prevent_any_assignment(
    guide: Path, options: list[str]
) -> None:
    guide.write_bytes(
        LABELED
        + b'- You MUST record. `IG0001`<a id="ig0001"></a>\r\n- You MAY add this.\r\n'
    )
    before = snapshot(guide)
    result = invoke(
        guide.parent, "assign", "--quiet", *options, "--prefix", "IG", str(guide)
    )
    assert result.returncode == 1
    assert result.stdout == b""
    assert b"duplicate identifier" in result.stderr
    assert snapshot(guide) == before


def test_unlabeled_lists_all_unlabeled_items_for_review(guide: Path) -> None:
    guide.write_bytes(
        SOURCE + b"- Explanation.\r\n\r\n## Reasoning\r\n\r\n- Other explanation.\r\n"
    )
    before = snapshot(guide)
    result = invoke(guide.parent, "unlabeled", "--prefix", "IG", str(guide))
    assert result.returncode == 0, result.stderr
    assert result.stdout == b"3: [Rules] You MUST validate.\n4: [Rules] Explanation.\n"
    assert result.stderr == b""
    assert snapshot(guide) == before


@pytest.mark.parametrize(
    "arguments",
    [
        ["check", "--prefix", "IG"],
        ["check", "guide.md"],
        ["check", "--prefix", "ig", "guide.md"],
        ["list", "--dry-run", "--prefix", "IG", "guide.md"],
        ["assign", "--prefix", "I1", "guide.md"],
    ],
)
def test_usage_errors(guide: Path, arguments: list[str]) -> None:
    result = invoke(guide.parent, *arguments)
    assert result.returncode == 2
    assert result.stdout == b""
    assert b"error:" in result.stderr


@pytest.mark.parametrize("source", [b"\xff", b"\xef\xbb\xbf" + SOURCE, SOURCE + b"\0"])
def test_invalid_encoding_is_reported_without_traceback(
    guide: Path, source: bytes
) -> None:
    guide.write_bytes(source)
    result = invoke(guide.parent, "assign", "--prefix", "IG", str(guide))
    assert result.returncode == 1
    assert result.stdout == b""
    assert b"Traceback" not in result.stderr
    assert guide.read_bytes() == source


@pytest.mark.parametrize("name", ["missing.md", "."])
def test_missing_files_and_directories_are_reported(guide: Path, name: str) -> None:
    result = invoke(guide.parent, "check", "--prefix", "IG", name)
    assert result.returncode == 1
    assert b"input must be a regular file" in result.stderr


@POSIX_ONLY
def test_assignment_preserves_permissions(guide: Path) -> None:
    guide.chmod(0o640)
    result = invoke(guide.parent, "assign", "--prefix", "IG", str(guide))
    assert result.returncode == 0, result.stderr
    assert stat.S_IMODE(guide.stat().st_mode) == 0o640


@POSIX_ONLY
@pytest.mark.parametrize("options", [[], ["--dry-run"]])
def test_assignment_refuses_symlinks(guide: Path, options: list[str]) -> None:
    link = guide.parent / "link.md"
    link.symlink_to(guide)
    before = snapshot(guide)
    result = invoke(guide.parent, "assign", *options, "--prefix", "IG", str(link))
    assert result.returncode == 1
    assert b"symbolic link" in result.stderr
    assert snapshot(guide) == before
