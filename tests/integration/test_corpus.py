# SPDX-FileCopyrightText: foundata GmbH <https://foundata.com>
# SPDX-License-Identifier: GPL-3.0-or-later

import difflib
import hashlib
import json

import pytest

from tests.support import FIXTURES, TRANSFORMER

CORPUS = FIXTURES / "corpus"
MANIFEST = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))
REPOSITORIES = [str(entry["repository"]) for entry in MANIFEST["readmes"]]
# Their screenshots are HTML images, which stripping refuses.
HTML_IMAGES = {"ansible-docsmith", "scanmole"}
pytestmark = pytest.mark.integration


def difference(expected: str, output: str) -> str:
    return "".join(
        difflib.unified_diff(
            expected.splitlines(keepends=True),
            output.splitlines(keepends=True),
            fromfile="expected",
            tofile="actual",
        )
    )


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
    assert not difference(expected, output), difference(expected, output)


@pytest.mark.parametrize("repository", REPOSITORIES)
def test_stripped_output_matches_the_frozen_expectations(repository: str) -> None:
    directory = CORPUS / repository
    source = (directory / "README.md").read_text(encoding="utf-8")

    def stripped() -> str:
        return TRANSFORMER.prepare_markdown(
            source,
            raw_base=f"https://raw.githubusercontent.com/foundata/{repository}/refs/heads/main",
            ui_base=f"https://github.com/foundata/{repository}/blob/main",
            collapse_header=True,
            strip_html=True,
            absolute_anchors=True,
            strict=True,
        )

    if repository in HTML_IMAGES:
        assert not (directory / "expected-stripped.md").exists()
        with pytest.raises(ValueError, match="<img> is raw HTML"):
            stripped()
        return
    expected = (directory / "expected-stripped.md").read_text(encoding="utf-8")
    output = stripped()
    assert not difference(expected, output), difference(expected, output)


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
