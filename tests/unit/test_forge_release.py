# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later

from pathlib import Path

import pytest

from releasing import forge_api, forge_release, processes
from releasing.artifacts import build_manifest, dump_manifest, load_manifest
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

### Fixed

- The thing that was broken.


[unreleased]: https://github.com/foundata/example/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/foundata/example/releases/tag/v1.0.0
"""


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ReleaseConfig:
    (tmp_path / "README.md").write_text("# Example\n", encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(CHANGELOG, encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "example"\nversion = "1.0.0"\n', encoding="utf-8"
    )
    monkeypatch.setattr(processes, "executable", lambda name: Path("/usr/bin") / name)
    monkeypatch.setattr(forge_api, "release_exists", lambda forge, tag: False)
    return ReleaseConfig(
        root=tmp_path, source=tmp_path / "pyproject.toml", repository="foundata/example"
    )


def with_artifacts(root: Path) -> Path:
    directory = root / "dist"
    directory.mkdir()
    (directory / "example-1.0.0.tar.gz").write_bytes(b"source distribution")
    manifest = build_manifest(
        [directory / "example-1.0.0.tar.gz"],
        repository="foundata/example",
        version="1.0.0",
        source_revision="a" * 40,
    )
    path = directory / "artifacts.json"
    path.write_text(dump_manifest(manifest), encoding="utf-8")
    return path


def test_the_notes_are_the_changelog_section(project: ReleaseConfig) -> None:
    prepared = forge_release.plan(project.root, project, FORGE, "1.0.0")
    assert prepared.notes == "### Fixed\n\n- The thing that was broken.\n"
    assert (prepared.tag, prepared.title, prepared.tool) == ("v1.0.0", "v1.0.0", "gh")
    assert prepared.assets == ()


def test_the_assets_are_the_manifest_and_its_files(project: ReleaseConfig) -> None:
    path = with_artifacts(project.root)
    prepared = forge_release.plan(
        project.root,
        project,
        FORGE,
        "1.0.0",
        manifest=load_manifest(path),
        manifest_path=path,
    )
    assert [asset.name for asset in prepared.assets] == [
        "artifacts.json",
        "example-1.0.0.tar.gz",
    ]


def test_a_version_the_changelog_does_not_document_is_refused(
    project: ReleaseConfig,
) -> None:
    with pytest.raises(forge_release.ForgeReleaseError, match="no changelog section"):
        forge_release.plan(project.root, project, FORGE, "9.9.9")


def test_an_existing_release_is_refused(
    project: ReleaseConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(forge_api, "release_exists", lambda forge, tag: True)
    with pytest.raises(forge_release.ForgeReleaseError, match="already has a release"):
        forge_release.plan(project.root, project, FORGE, "1.0.0")
    # Offline does not ask, so it cannot refuse on that ground.
    assert (
        forge_release.plan(project.root, project, FORGE, "1.0.0", offline=True).tag
        == "v1.0.0"
    )


def test_altered_artifacts_are_refused(project: ReleaseConfig) -> None:
    path = with_artifacts(project.root)
    (path.parent / "example-1.0.0.tar.gz").write_bytes(b"tampered")
    with pytest.raises(forge_release.ForgeReleaseError, match="SHA-256 differs"):
        forge_release.plan(
            project.root,
            project,
            FORGE,
            "1.0.0",
            manifest=load_manifest(path),
            manifest_path=path,
        )


def test_an_unknown_forge_is_refused(project: ReleaseConfig) -> None:
    other = Forge("gitea", "foundata/example", "https://g", "https://r", "https://a")
    with pytest.raises(forge_release.ForgeReleaseError, match="no release tool"):
        forge_release.plan(project.root, project, other, "1.0.0")


def test_a_collection_takes_its_notes_from_the_collection_changelog(
    project: ReleaseConfig,
) -> None:
    (project.root / "changelogs").mkdir()
    (project.root / "changelogs" / "changelog.yaml").write_text(
        "releases:\n  1.0.0:\n    changes:\n      bugfixes:\n"
        "        - 'The thing that was broken.'\n",
        encoding="utf-8",
    )
    collection = ReleaseConfig(
        root=project.root,
        source=project.source,
        repository="foundata/example",
        changelog="antsibull",
    )
    prepared = forge_release.plan(project.root, collection, FORGE, "1.0.0")
    assert prepared.notes == "### Bugfixes\n\n- The thing that was broken.\n"


def test_a_collection_without_that_version_is_refused(
    project: ReleaseConfig,
) -> None:
    (project.root / "changelogs").mkdir()
    (project.root / "changelogs" / "changelog.yaml").write_text(
        "releases: {}\n", encoding="utf-8"
    )
    collection = ReleaseConfig(
        root=project.root,
        source=project.source,
        repository="foundata/example",
        changelog="antsibull",
    )
    with pytest.raises(forge_release.ForgeReleaseError, match=r"no release 1\.0\.0"):
        forge_release.plan(project.root, collection, FORGE, "1.0.0")


def test_the_write_is_delegated_and_the_notes_file_is_transient(
    project: ReleaseConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = forge_release.plan(project.root, project, FORGE, "1.0.0")
    seen: dict[str, object] = {}

    def record(argv: list[str], **kwargs: object) -> str:
        seen["argv"] = argv
        notes = Path(argv[argv.index("--notes-file") + 1])
        seen["notes"] = notes.read_text(encoding="utf-8")
        return ""

    monkeypatch.setattr(processes, "run", record)
    argv = forge_release.execute(project.root, prepared)
    assert argv[1:4] == ["release", "create", "v1.0.0"]
    assert seen["notes"] == prepared.notes
    # No credential is ever an argument, and the notes do not outlive the call.
    assert not any("token" in item.lower() for item in argv)
    assert list(project.root.glob(".releasing-notes-*")) == []


def test_dry_run_runs_nothing(
    project: ReleaseConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*args: object, **kwargs: object) -> object:
        raise AssertionError("a dry run must not create anything")

    monkeypatch.setattr(processes, "run", refuse)
    prepared = forge_release.plan(project.root, project, FORGE, "1.0.0")
    argv = forge_release.execute(project.root, prepared, dry_run=True)
    assert argv[1:4] == ["release", "create", "v1.0.0"]
    assert list(project.root.glob(".releasing-notes-*")) == []
