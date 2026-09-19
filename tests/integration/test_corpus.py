# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later

import difflib
import hashlib
import json

import pytest

from tests.support import FIXTURES, TRANSFORMER

CORPUS = FIXTURES / "corpus"
MANIFEST = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))
REPOSITORIES = [str(entry["repository"]) for entry in MANIFEST["readmes"]]
pytestmark = pytest.mark.integration


@pytest.mark.parametrize("repository", REPOSITORIES)
@pytest.mark.parametrize("simplify", [False, True], ids=["default", "simplified"])
def test_output_matches_the_frozen_expectations(
    repository: str, simplify: bool
) -> None:
    directory = CORPUS / repository
    source = (directory / "README.md").read_text(encoding="utf-8")
    expected = (
        directory / ("expected-simplified.md" if simplify else "expected.md")
    ).read_text(encoding="utf-8")
    output = TRANSFORMER.prepare_markdown(
        source,
        raw_base=f"https://raw.githubusercontent.com/foundata/{repository}/refs/heads/main",
        ui_base=f"https://github.com/foundata/{repository}/blob/main",
        simplify=simplify,
        strict=True,
    )
    difference = "".join(
        difflib.unified_diff(
            expected.splitlines(keepends=True),
            output.splitlines(keepends=True),
            fromfile="expected",
            tofile="actual",
        )
    )
    assert not difference, difference


def test_snapshot_provenance() -> None:
    assert len(REPOSITORIES) == 21
    for entry in MANIFEST["readmes"]:
        assert (
            hashlib.sha256(
                (CORPUS / entry["repository"] / "README.md").read_bytes()
            ).hexdigest()
            == entry["sha256"]
        )
        assert len(entry["revision"]) == 40
