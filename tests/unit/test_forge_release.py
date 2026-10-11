# SPDX-FileCopyrightText: foundata GmbH <https://foundata.com>
# SPDX-License-Identifier: GPL-3.0-or-later

import tempfile
from dataclasses import replace
from pathlib import Path

import pytest

from releasing import forge_api, forge_release, processes, reporting
from releasing.artifacts import (
    ArtifactError,
    build_manifest,
    dump_manifest,
    load_manifest,
)
from releasing.config import ReleaseConfig
from releasing.forges import Forge

FORGE = Forge(
    "github",
    "foundata/example",
    "https://github.com",
    "https://raw.githubusercontent.com",
    "https://api.github.com",
    tool="gh",
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

    def git(root: Path, *args: str) -> str:
        if args[0] == "rev-parse":
            return "a" * 40
        if args[0] == "ls-tree":
            return args[-1] if (root / args[-1]).is_file() else ""
        assert args[0] == "show"
        return (root / args[1].split(":", 1)[1]).read_text(encoding="utf-8")

    monkeypatch.setattr(processes, "git", git)
    return ReleaseConfig(
        root=tmp_path, source=tmp_path / "pyproject.toml", repository="foundata/example"
    )


def with_artifacts(root: Path, *, version: str = "1.0.0") -> Path:
    directory = root / "dist"
    directory.mkdir()
    (directory / f"example-{version}.tar.gz").write_bytes(b"source distribution")
    manifest = build_manifest(
        [directory / f"example-{version}.tar.gz"],
        repository="foundata/example",
        version=version,
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


@pytest.mark.parametrize("manifest_version", ["0.9.0", "1.0.1"])
def test_artifacts_for_another_version_are_refused(
    project: ReleaseConfig, manifest_version: str
) -> None:
    path = with_artifacts(project.root, version=manifest_version)
    with pytest.raises(
        forge_release.ForgeReleaseError, match="manifest records version"
    ):
        forge_release.plan(
            project.root,
            project,
            FORGE,
            "1.0.0",
            manifest=load_manifest(path),
            manifest_path=path,
        )


def test_a_compatible_manifest_without_a_version_remains_usable(
    project: ReleaseConfig,
) -> None:
    path = with_artifacts(project.root)
    manifest = replace(load_manifest(path), version="")
    path.write_text(dump_manifest(manifest), encoding="utf-8")
    prepared = forge_release.plan(
        project.root,
        project,
        FORGE,
        "1.0.0",
        manifest=manifest,
        manifest_path=path,
    )
    assert prepared.tag == "v1.0.0"
    assert prepared.assets[1].name == "example-1.0.0.tar.gz"


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


@pytest.mark.parametrize("filename", ["artifacts.json", "example-1.0.0.tar.gz"])
def test_execution_refuses_inputs_changed_after_planning(
    project: ReleaseConfig, monkeypatch: pytest.MonkeyPatch, filename: str
) -> None:
    path = with_artifacts(project.root)
    prepared = forge_release.plan(
        project.root,
        project,
        FORGE,
        "1.0.0",
        manifest=load_manifest(path),
        manifest_path=path,
    )
    (path.parent / filename).write_bytes(b"changed after planning")

    def refuse(*args: object, **kwargs: object) -> str:
        pytest.fail("changed release inputs must not reach gh")

    monkeypatch.setattr(processes, "run", refuse)
    with pytest.raises(ArtifactError, match="SHA-256 changed since planning"):
        forge_release.execute(project.root, prepared)


def test_an_unknown_forge_is_refused(project: ReleaseConfig) -> None:
    other = Forge("gitea", "foundata/example", "https://g", "https://r", "https://a")
    with pytest.raises(forge_release.ForgeReleaseError, match="no release tool"):
        forge_release.plan(project.root, project, other, "1.0.0")


def test_the_manifest_attachment_must_describe_the_manifest_that_was_checked(
    project: ReleaseConfig,
) -> None:
    path = with_artifacts(project.root)
    manifest = load_manifest(path)
    path.write_text(
        dump_manifest(replace(manifest, repository="other/project")), encoding="utf-8"
    )
    with pytest.raises(forge_release.ForgeReleaseError, match="manifest changed"):
        forge_release.plan(
            project.root, project, FORGE, "1.0.0", manifest=manifest, manifest_path=path
        )


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
    monkeypatch.setenv("GH_REPO", "other/wrong-project")
    monkeypatch.setenv("GH_HOST", "other.example")
    prepared = forge_release.plan(project.root, project, FORGE, "1.0.0")
    seen: dict[str, object] = {}

    def record(argv: list[str], **kwargs: object) -> str:
        seen["argv"] = argv
        notes = Path(argv[argv.index("--notes-file") + 1])
        seen["notes"] = notes.read_text(encoding="utf-8")
        return "https://github.com/foundata/example/releases/tag/v1.0.0\n"

    monkeypatch.setattr(processes, "run", record)
    reported = forge_release.execute(project.root, prepared)
    argv = seen["argv"]
    assert isinstance(argv, list)
    assert argv[1:4] == ["release", "create", "v1.0.0"]
    assert argv[argv.index("--repo") + 1] == "github.com/foundata/example"
    assert "--verify-tag" in argv
    assert seen["notes"] == prepared.notes
    # The forge's own tool reports where the entry lives; that is the product.
    assert reported == "https://github.com/foundata/example/releases/tag/v1.0.0"
    # No credential is ever an argument, and the notes do not outlive the call.
    assert not any("token" in item.lower() for item in argv)
    assert list(project.root.glob(".releasing-notes-*")) == []


def test_dry_run_runs_nothing(
    project: ReleaseConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*args: object, **kwargs: object) -> object:
        raise AssertionError("a dry run must not create anything")

    monkeypatch.setattr(processes, "run", refuse)
    monkeypatch.setattr(tempfile, "TemporaryDirectory", refuse)
    prepared = forge_release.plan(project.root, project, FORGE, "1.0.0")
    narrated: list[str] = []
    monkeypatch.setattr(
        reporting,
        "command",
        lambda argv, **kwargs: narrated.append(reporting.render(argv)),
    )

    assert forge_release.execute(project.root, prepared, dry_run=True) == ""
    assert "gh release create v1.0.0" in narrated[0]
    assert "--repo github.com/foundata/example" in narrated[0]
    assert "--verify-tag" in narrated[0]
    assert list(project.root.glob(".releasing-notes-*")) == []


@pytest.mark.parametrize("fails", [False, True])
def test_notes_staging_preserves_existing_files_and_cleans_up(
    project: ReleaseConfig, monkeypatch: pytest.MonkeyPatch, fails: bool
) -> None:
    existing = project.root / ".releasing-notes-v1.0.0"
    existing.write_bytes(b"existing user notes\n")
    prepared = forge_release.plan(project.root, project, FORGE, "1.0.0")
    staged: list[Path] = []

    def run(argv: list[str], **kwargs: object) -> str:
        notes = Path(argv[argv.index("--notes-file") + 1])
        staged.append(notes)
        assert notes.read_text(encoding="utf-8") == prepared.notes
        if fails:
            raise processes.ProcessError("release refused")
        return "https://github.com/foundata/example/releases/tag/v1.0.0\n"

    monkeypatch.setattr(processes, "run", run)
    if fails:
        with pytest.raises(processes.ProcessError, match="release refused"):
            forge_release.execute(project.root, prepared)
    else:
        assert forge_release.execute(project.root, prepared).endswith("/v1.0.0")
    assert existing.read_bytes() == b"existing user notes\n"
    assert len(staged) == 1
    assert not staged[0].exists()
    assert not staged[0].parent.exists()


def test_notes_staging_accepts_a_tag_with_slashes(
    project: ReleaseConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = replace(project, tag_format="releases/v{version}")
    prepared = forge_release.plan(project.root, config, FORGE, "1.0.0")

    def run(argv: list[str], **kwargs: object) -> str:
        assert argv[3] == "releases/v1.0.0"
        notes = Path(argv[argv.index("--notes-file") + 1])
        assert notes.read_text(encoding="utf-8") == prepared.notes
        return "created"

    monkeypatch.setattr(processes, "run", run)
    assert forge_release.execute(project.root, prepared) == "created"


def test_a_notes_write_failure_cleans_up_its_directory(
    project: ReleaseConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = forge_release.plan(project.root, project, FORGE, "1.0.0")
    staged: list[Path] = []

    def refuse_write(path: Path, *args: object, **kwargs: object) -> int:
        staged.append(path)
        raise OSError("disk full")

    def refuse_run(*args: object, **kwargs: object) -> str:
        raise AssertionError("cannot publish without the notes")

    monkeypatch.setattr(Path, "write_text", refuse_write)
    monkeypatch.setattr(processes, "run", refuse_run)
    with pytest.raises(forge_release.ForgeReleaseError, match="disk full"):
        forge_release.execute(project.root, prepared)
    assert len(staged) == 1
    assert not staged[0].parent.exists()


@pytest.mark.parametrize("shadow_files", [False, True])
def test_relative_assets_keep_the_verified_bytes_when_execution_changes_directory(
    project: ReleaseConfig, monkeypatch: pytest.MonkeyPatch, shadow_files: bool
) -> None:
    caller = project.root / "caller"
    caller.mkdir()
    path = with_artifacts(caller)
    expected = [path.read_bytes(), b"source distribution"]
    if shadow_files:
        (project.root / "dist").mkdir()
        (project.root / "dist" / "artifacts.json").write_bytes(b"wrong manifest")
        (project.root / "dist" / "example-1.0.0.tar.gz").write_bytes(b"wrong artifact")
    monkeypatch.chdir(caller)
    relative = Path("dist/artifacts.json")
    prepared = forge_release.plan(
        project.root,
        project,
        FORGE,
        "1.0.0",
        manifest=load_manifest(relative),
        manifest_path=relative,
    )

    def read_assets(argv: list[str], *, cwd: Path, **kwargs: object) -> str:
        paths = argv[argv.index("--notes-file") + 2 :]
        assert [(cwd / value).read_bytes() for value in paths] == expected
        return "created"

    monkeypatch.setattr(processes, "run", read_assets)
    assert forge_release.execute(project.root, prepared) == "created"
