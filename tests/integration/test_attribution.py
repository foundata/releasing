# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import subprocess
from pathlib import Path

import pytest

from releasing import attribution

pytestmark = pytest.mark.integration
GIT_ENV = {
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
    # Git transport stays on the local filesystem in these tests.
    "GIT_ALLOW_PROTOCOL": "file",
}
AWKWARD = """release: prepare 1.0.0

A body with a blank line above, a colon: and trailing whitespace.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
"""


def git(cwd: Path, *arguments: str, stdin: str | None = None) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *arguments],
        env={**os.environ, **GIT_ENV},
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
        input=stdin,
    ).stdout


@pytest.fixture
def history(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(root)],
        env={**os.environ, **GIT_ENV},
        check=True,
        timeout=60,
        capture_output=True,
    )
    (root / "a.txt").write_text("a\n", encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "project: establish it")
    (root / "b.txt").write_text("b\n", encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-q", "-F", "-", stdin=AWKWARD)
    return root


def test_a_multi_line_message_survives_being_read_back(history: Path) -> None:
    # The body carries blank lines and colons, so the record separators have to
    # come from git rather than from splitting on punctuation.
    commits = attribution.read(history, ["HEAD"])

    assert len(commits) == 1
    assert commits[0].subject == "release: prepare 1.0.0"
    assert commits[0].author == "Test <test@example.invalid>"
    assert "A body with a blank line above" in commits[0].message
    assert [item.rule for item in attribution.findings(commits)] == ["co-authored-by"]


def test_one_revision_does_not_drag_in_its_ancestors(history: Path) -> None:
    assert len(attribution.read(history, ["HEAD"])) == 1
    assert len(attribution.read(history, ["HEAD~1..HEAD"])) == 1
    assert len(attribution.read(history, ["HEAD", "HEAD~1"])) == 2


def test_a_commit_named_twice_is_read_once(history: Path) -> None:
    # A release commit is both the tagged revision and part of what a push
    # would send, so it must not be reported twice.
    commits = attribution.read(history, ["HEAD", "HEAD~1..HEAD"])

    assert [commit.revision for commit in commits] == [
        git(history, "rev-parse", "HEAD").strip()
    ]


def test_an_unknown_revision_is_reported_as_such(history: Path) -> None:
    with pytest.raises(attribution.AttributionError, match="cannot read the commits"):
        attribution.read(history, ["no-such-revision"])


def test_nothing_to_read_is_not_an_error(history: Path) -> None:
    assert attribution.read(history, []) == []
    assert attribution.read(history, ["HEAD..HEAD"]) == []


def test_what_a_named_remote_already_has_is_left_out(
    history: Path, tmp_path: Path
) -> None:
    remote = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "-q", "--bare", str(remote)],
        env={**os.environ, **GIT_ENV},
        check=True,
        timeout=60,
        capture_output=True,
    )
    git(history, "remote", "add", "origin", str(remote))
    git(history, "push", "-q", "origin", "main")
    git(history, "commit", "-q", "--allow-empty", "-m", "chore: after the push")

    assert len(attribution.read(history, ["main"], walk=True)) == 3
    assert len(attribution.read(history, ["main"], walk=True, remote="origin")) == 1
    # Without a walk a plain selector is still exactly one commit.
    assert len(attribution.read(history, ["main"])) == 1
    assert attribution.read(history, ["HEAD~1"], remote="origin") == []
    # An unknown remote excludes nothing rather than everything.
    assert len(attribution.read(history, ["HEAD~1"], remote="absent")) == 1
