# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later

import difflib
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from tests.support import FIXTURES, ROOT, TRANSFORMER

CORPUS = FIXTURES / "corpus"
MANIFEST = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))
REPOSITORIES = [str(entry["repository"]) for entry in MANIFEST["readmes"]]
pytestmark = pytest.mark.integration


@pytest.mark.parametrize("repository", REPOSITORIES)
@pytest.mark.parametrize("simplify", [False, True], ids=["default", "simplified"])
def test_python_matches_frozen_shell_output(repository: str, simplify: bool) -> None:
    directory = CORPUS / repository
    source = (directory / "README.md").read_text(encoding="utf-8")
    shell = (directory / ("shell-simplified.md" if simplify else "shell.md")).read_text(
        encoding="utf-8"
    )
    output = TRANSFORMER.prepare_markdown(
        source,
        raw_base=f"https://raw.githubusercontent.com/foundata/{repository}/refs/heads/main",
        ui_base=f"https://github.com/foundata/{repository}/blob/main",
        simplify=simplify,
        strict=True,
    )
    difference = "".join(
        difflib.unified_diff(
            shell.splitlines(keepends=True),
            output.splitlines(keepends=True),
            fromfile="shell",
            tofile="python",
        )
    )
    assert not difference, difference


@pytest.mark.parametrize("repository", REPOSITORIES)
@pytest.mark.parametrize("simplify", [False, True], ids=["default", "simplified"])
def test_frozen_baseline_matches_unchanged_shell(
    repository: str, simplify: bool, tmp_path: Path
) -> None:
    directory = CORPUS / repository
    copied = tmp_path / "README.md"
    copied.write_bytes((directory / "README.md").read_bytes())
    subprocess.run(
        [
            "bash",
            str(ROOT / "release-prepare-markdown.sh"),
            "-o",
            "foundata",
            "-r",
            repository,
            "-b",
            "main",
            *(["-s"] if simplify else []),
            str(copied),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    assert (
        copied.read_bytes()
        == (
            directory / ("shell-simplified.md" if simplify else "shell.md")
        ).read_bytes()
    )


def test_snapshot_provenance_and_shell_identity() -> None:
    assert (
        hashlib.sha256((ROOT / "release-prepare-markdown.sh").read_bytes()).hexdigest()
        == MANIFEST["shell_sha256"]
    )
    assert len(REPOSITORIES) == 21
    for entry in MANIFEST["readmes"]:
        assert (
            hashlib.sha256(
                (CORPUS / entry["repository"] / "README.md").read_bytes()
            ).hexdigest()
            == entry["sha256"]
        )
        assert len(entry["revision"]) == 40
