# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later

from collections.abc import Iterable
from dataclasses import replace
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


def details(report: status.Status) -> dict[str, str]:
    return {step.name: step.detail for step in report.steps}


def states(report: status.Status) -> dict[str, str]:
    return {step.name: step.state for step in report.steps}


@pytest.fixture
def ready_project(
    project: ReleaseConfig, monkeypatch: pytest.MonkeyPatch
) -> ReleaseConfig:
    arrange(
        monkeypatch,
        tag_state(
            revision=REVISION,
            annotated=True,
            message="version 1.0.0",
            remote_revision="t" * 40,
        ),
        published=[verify.IndexFile("example-1.0.0.tar.gz", "b" * 64)],
    )
    return project


def forge_responses(
    monkeypatch: pytest.MonkeyPatch, responses: Iterable[bool | forge_api.ForgeError]
) -> list[str]:
    answers = iter(responses)
    events: list[str] = []

    def exists(forge: Forge, tag: str) -> bool:
        assert (forge, tag) == (FORGE, "v1.0.0")
        events.append("query")
        answer = next(answers)
        if isinstance(answer, forge_api.ForgeError):
            raise answer
        return answer

    def sleep(seconds: float) -> None:
        events.append(f"sleep:{seconds:g}")

    monkeypatch.setattr(forge_api, "release_exists", exists)
    monkeypatch.setattr(status, "sleep", sleep)
    return events


@pytest.mark.parametrize("missing", [0, 1, 2, 3])
def test_forge_checks_stop_as_soon_as_the_release_appears(
    ready_project: ReleaseConfig,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    missing: int,
) -> None:
    events = forge_responses(monkeypatch, [False] * missing + [True])

    report = status.collect(
        ready_project.root, ready_project, FORGE, "1.0.0", manifest=MANIFEST
    )

    assert report.complete
    assert details(report)["forge release"] == "github has a release for v1.0.0"
    assert events == ["query"] + ["sleep:5", "query"] * missing
    output = capsys.readouterr()
    assert (output.out, output.err) == ("", "")


def test_forge_release_stays_pending_after_three_retries(
    ready_project: ReleaseConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    events = forge_responses(monkeypatch, [False] * 4)

    report = status.collect(
        ready_project.root, ready_project, FORGE, "1.0.0", manifest=MANIFEST
    )

    assert states(report)["forge release"] == status.PENDING
    assert details(report)["forge release"] == (
        "github release for v1.0.0 is not visible after 4 checks"
    )
    assert not report.complete
    assert report.broken == ()
    assert events == ["query"] + ["sleep:5", "query"] * 3


@pytest.mark.parametrize("missing", [0, 1])
@pytest.mark.parametrize("error", ["HTTP 403", "HTTP 429", "HTTP 500", "timed out"])
def test_forge_errors_stop_retries_and_leave_the_state_unknown(
    ready_project: ReleaseConfig,
    monkeypatch: pytest.MonkeyPatch,
    missing: int,
    error: str,
) -> None:
    events = forge_responses(
        monkeypatch, [False] * missing + [forge_api.ForgeError(error)]
    )

    report = status.collect(
        ready_project.root, ready_project, FORGE, "1.0.0", manifest=MANIFEST
    )

    assert states(report)["forge release"] == status.UNKNOWN
    assert details(report)["forge release"] == error
    assert events == ["query"] + ["sleep:5", "query"] * missing


def test_waiting_can_be_disabled_for_an_otherwise_finished_release(
    ready_project: ReleaseConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    events = forge_responses(monkeypatch, [False])

    report = status.collect(
        ready_project.root,
        ready_project,
        FORGE,
        "1.0.0",
        manifest=MANIFEST,
        wait_for_forge=False,
    )

    assert states(report)["forge release"] == status.PENDING
    assert details(report)["forge release"] == "github has no release for v1.0.0"
    assert events == ["query"]


@pytest.mark.parametrize(
    "unfinished",
    ["changelog", "tag", "tag pushed", "artifact revision", "index"],
)
def test_another_unfinished_step_prevents_waiting_for_the_forge(
    ready_project: ReleaseConfig,
    monkeypatch: pytest.MonkeyPatch,
    unfinished: str,
) -> None:
    manifest = MANIFEST
    if unfinished == "changelog":
        (ready_project.root / "CHANGELOG.md").write_text(
            "# Changelog\n", encoding="utf-8"
        )
    elif unfinished == "tag":
        monkeypatch.setattr(tagging, "state", lambda *args, **kwargs: tag_state())
    elif unfinished == "tag pushed":
        monkeypatch.setattr(processes, "git", lambda *args, **kwargs: "")
    elif unfinished == "artifact revision":
        manifest = replace(MANIFEST, source_revision="c" * 40)
    else:
        monkeypatch.setattr(verify, "index_files", lambda *args: [])
    events = forge_responses(monkeypatch, [False])

    report = status.collect(
        ready_project.root, ready_project, FORGE, "1.0.0", manifest=manifest
    )

    assert states(report)[unfinished] != status.OK
    assert states(report)["forge release"] == status.PENDING
    assert events == ["query"]


def test_an_unknown_index_prevents_waiting_for_the_forge(
    ready_project: ReleaseConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    events = forge_responses(monkeypatch, [False])

    report = status.collect(ready_project.root, ready_project, FORGE, "1.0.0")

    assert states(report)["index"] == status.UNKNOWN
    assert events == ["query"]


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
    monkeypatch.setattr(status, "sleep", refuse)
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


def test_the_report_names_the_remote_it_asked(
    project: ReleaseConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A fork releases to a remote that is not called origin, so "not on the
    # remote" has to say which one was asked.
    arrange(
        monkeypatch,
        tag_state(revision=REVISION, annotated=True, message="version 1.0.0"),
    )
    asked: list[str] = []

    def record(root: Path, *arguments: str, **kwargs: object) -> str:
        asked.append(" ".join(arguments))
        return ""

    monkeypatch.setattr(processes, "git", record)

    report = status.collect(project.root, project, FORGE, "1.0.0", remote="upstream")

    assert "ls-remote --tags upstream refs/tags/v1.0.0" in asked
    assert details(report)["tag pushed"] == "v1.0.0 is not on upstream"
