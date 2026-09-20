# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later

from pathlib import Path

import pytest

from releasing import forge_api, processes, status, verify
from releasing import tag as tagging
from releasing.artifacts import Manifest, ManifestEntry
from releasing.config import ReleaseConfig
from releasing.forges import Forge

FORGE = Forge(
    "github",
    "foundata/example",
    "https://github.com",
    "https://raw.githubusercontent.com",
    "https://api.github.com",
)
CHANGELOG = """# Changelog

## [Unreleased]

- Nothing worth mentioning right now.


## [1.0.0] - 2026-09-01

- All functionality.


[unreleased]: https://github.com/foundata/example/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/foundata/example/releases/tag/v1.0.0
"""
REVISION = "a" * 40
MANIFEST = Manifest(
    repository="foundata/example",
    version="1.0.0",
    source_revision=REVISION,
    artifacts=(ManifestEntry("example-1.0.0.tar.gz", "b" * 64, 10),),
    created="2026-09-01T00:00:00+00:00",
)


@pytest.fixture
def project(tmp_path: Path) -> ReleaseConfig:
    (tmp_path / "README.md").write_text("# Example\n", encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(CHANGELOG, encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "example"\nversion = "1.0.0"\n', encoding="utf-8"
    )
    return ReleaseConfig(
        root=tmp_path, source=tmp_path / "pyproject.toml", repository="foundata/example"
    )


def arrange(
    monkeypatch: pytest.MonkeyPatch,
    tag_state: tagging.TagState,
    *,
    local_object: str = "t" * 40,
    published: list[verify.IndexFile] | None = None,
    index_error: str | None = None,
    remote_unreachable: str | None = None,
    release_exists: bool = False,
    forge_error: str | None = None,
) -> None:
    monkeypatch.setattr(tagging, "state", lambda *args, **kwargs: tag_state)

    def git(root: object, *arguments: str, **kwargs: object) -> str:
        if arguments and arguments[0] == "ls-remote":
            if remote_unreachable is not None:
                raise processes.ProcessError(remote_unreachable)
            if tag_state.remote_revision is None:
                return ""
            return f"{tag_state.remote_revision}\trefs/tags/{tag_state.tag}\n"
        return local_object + "\n"

    monkeypatch.setattr(processes, "git", git)

    def files(index: str, name: str, version: str) -> list[verify.IndexFile]:
        if index_error is not None:
            raise verify.VerificationError(index_error)
        return published or []

    monkeypatch.setattr(verify, "index_files", files)

    def exists(forge: Forge, tag: str) -> bool:
        if forge_error is not None:
            raise forge_api.ForgeError(forge_error)
        return release_exists

    monkeypatch.setattr(forge_api, "release_exists", exists)


def tag_state(**overrides: object) -> tagging.TagState:
    values: dict[str, object] = {
        "tag": "v1.0.0",
        "revision": None,
        "annotated": False,
        "message": "",
        "remote_revision": None,
        "release_exists": False,
    }
    values.update(overrides)
    return tagging.TagState(**values)  # type: ignore[arg-type]


def states(report: status.Status) -> dict[str, str]:
    return {step.name: step.state for step in report.steps}


def test_a_finished_release_is_complete(
    project: ReleaseConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    arrange(
        monkeypatch,
        tag_state(
            revision=REVISION,
            annotated=True,
            message="version 1.0.0",
            remote_revision="t" * 40,
        ),
        published=[verify.IndexFile("example-1.0.0.tar.gz", "b" * 64)],
        release_exists=True,
    )
    report = status.collect(project.root, project, FORGE, "1.0.0", manifest=MANIFEST)
    assert states(report) == {
        "changelog": status.OK,
        "tag": status.OK,
        "tag pushed": status.OK,
        "artifact revision": status.OK,
        "index": status.OK,
        "forge release": status.OK,
    }
    assert report.complete
    assert report.broken == ()


def test_a_release_in_progress_is_pending_but_not_broken(
    project: ReleaseConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    arrange(monkeypatch, tag_state(), index_error="not published")
    report = status.collect(project.root, project, FORGE, "1.0.0", manifest=MANIFEST)
    assert states(report)["tag"] == status.PENDING
    assert states(report)["tag pushed"] == status.PENDING
    assert states(report)["index"] == status.PENDING
    assert states(report)["forge release"] == status.PENDING
    assert not report.complete
    assert report.broken == ()


def test_a_version_the_changelog_does_not_document_is_pending(
    project: ReleaseConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    arrange(monkeypatch, tag_state(), index_error="not published")
    report = status.collect(project.root, project, FORGE, "2.0.0")
    assert states(report)["changelog"] == status.PENDING
    assert report.broken == ()


def test_a_mismatch_is_reported_as_needing_attention(
    project: ReleaseConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    arrange(
        monkeypatch,
        tag_state(
            revision="c" * 40,
            annotated=True,
            message="version 1.0.0",
            remote_revision="other",
        ),
        published=[verify.IndexFile("example-1.0.0.tar.gz", "9" * 64)],
        release_exists=True,
    )
    report = status.collect(project.root, project, FORGE, "1.0.0", manifest=MANIFEST)
    names = {step.name for step in report.broken}
    assert names == {"tag pushed", "artifact revision", "index"}
    assert not report.complete
    detail = {step.name: step.detail for step in report.steps}
    assert "built from " + "a" * 12 in detail["artifact revision"]
    assert "published digest differs" in detail["index"]


def test_a_lightweight_tag_needs_attention(
    project: ReleaseConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    arrange(monkeypatch, tag_state(revision=REVISION), index_error="not published")
    assert states(status.collect(project.root, project, FORGE, "1.0.0"))["tag"] == (
        status.PROBLEM
    )


def test_an_unreachable_service_is_unknown_rather_than_broken(
    project: ReleaseConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    arrange(
        monkeypatch,
        tag_state(revision=REVISION, annotated=True, message="version 1.0.0"),
        index_error="connection refused",
        forge_error="connection refused",
    )
    report = status.collect(project.root, project, FORGE, "1.0.0", manifest=MANIFEST)
    assert states(report)["index"] == status.UNKNOWN
    assert states(report)["forge release"] == status.UNKNOWN
    assert not report.complete
    assert report.broken == ()


def test_offline_queries_nothing_remote(
    project: ReleaseConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*args: object, **kwargs: object) -> object:
        raise AssertionError("the network must not be touched")

    monkeypatch.setattr(verify, "index_files", refuse)
    monkeypatch.setattr(forge_api, "release_exists", refuse)
    monkeypatch.setattr(tagging, "state", lambda *a, **k: tag_state())
    report = status.collect(project.root, project, FORGE, "1.0.0", offline=True)
    assert states(report)["index"] == status.UNKNOWN
    assert states(report)["forge release"] == status.UNKNOWN


def test_without_a_manifest_the_index_cannot_be_identified(
    project: ReleaseConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    arrange(monkeypatch, tag_state())
    report = status.collect(project.root, project, FORGE, "1.0.0")
    assert states(report)["index"] == status.UNKNOWN
    assert "--manifest" in {step.name: step.detail for step in report.steps}["index"]


def test_an_unreachable_remote_leaves_the_push_state_unknown(
    project: ReleaseConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The report still shows everything it could determine locally.
    arrange(
        monkeypatch,
        tag_state(revision=REVISION, annotated=True, message="version 1.0.0"),
        remote_unreachable="git timed out after 20s",
        index_error="not published",
    )
    report = status.collect(project.root, project, FORGE, "1.0.0")
    assert states(report)["tag"] == status.OK
    assert states(report)["tag pushed"] == status.UNKNOWN
    assert report.broken == ()
    assert not report.complete
