# SPDX-FileCopyrightText: foundata GmbH <https://foundata.com>
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from releasing import artifacts
from tests.support import POSIX_ONLY, captured, write_lf

pytestmark = pytest.mark.integration
GIT_ENV = {
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
    "GIT_ALLOW_PROTOCOL": "file",
}
RELEASE_URL = "https://github.com/foundata/example/releases/tag/v1.0.0"
FAKE_GH = """import json
import os
import sys
from pathlib import Path

arguments = sys.argv[1:]
assert arguments[:2] == ["release", "create"], arguments
notes_index = arguments.index("--notes-file") + 1
notes = Path(arguments[notes_index])
assets = [Path(value) for value in arguments[notes_index + 1:]]
for source in json.loads(os.environ.get("FAKE_GH_MUTATE", "[]")):
    Path(source).write_bytes(b"changed while the uploader runs")
Path(os.environ["FAKE_GH_RECORD"]).write_text(json.dumps({
    "arguments": arguments,
    "cwd": str(Path.cwd()),
    "notes_path": str(notes),
    "notes": notes.read_text(encoding="utf-8"),
    "assets": {path.name: path.read_bytes().hex() for path in assets},
}), encoding="utf-8")
if error := os.environ.get("FAKE_GH_ERROR"):
    print(error, file=sys.stderr)
    sys.exit(7)
print("https://github.com/foundata/example/releases/tag/v1.0.0")
"""


def git(cwd: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *arguments],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    ).stdout


def release(root: Path, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [
            sys.executable,
            "-I",
            "-m",
            "releasing",
            "forge",
            "release-create",
            "1.0.0",
            "--project",
            str(root),
            "--offline",
            *arguments,
        ],
        cwd=root.parent,
        capture_output=True,
        timeout=60,
        check=False,
    )


@pytest.fixture
def fake_gh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    programs = tmp_path / "fake programs"
    programs.mkdir()
    script = programs / "fake_gh.py"
    write_lf(script, FAKE_GH)
    if sys.platform == "win32":
        write_lf(
            programs / "gh.cmd", f'@echo off\n"{sys.executable}" -I "{script}" %*\n'
        )
    else:
        executable = programs / "gh"
        write_lf(
            executable,
            f"#!/bin/sh\nexec {shlex.quote(sys.executable)} -I "
            f'{shlex.quote(str(script))} "$@"\n',
        )
        executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(programs) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("GH_REPO", "unrelated/wrong-project")
    monkeypatch.setenv("GH_HOST", "wrong-forge.invalid")
    monkeypatch.setenv("GH_CONFIG_DIR", str(tmp_path / "gh-config"))
    monkeypatch.delenv("FAKE_GH_ERROR", raising=False)
    monkeypatch.delenv("FAKE_GH_MUTATE", raising=False)
    record = tmp_path / "gh-call.json"
    monkeypatch.setenv("FAKE_GH_RECORD", str(record))
    staging = tmp_path / "staged notes"
    staging.mkdir()
    for name in ("TMPDIR", "TMP", "TEMP"):
        monkeypatch.setenv(name, str(staging))
    return record


@pytest.fixture
def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for key, value in GIT_ENV.items():
        monkeypatch.setenv(key, value)
    root = tmp_path / "project checkout"
    root.mkdir()
    write_lf(root / "README.md", "# Example\n")
    write_lf(
        root / "CHANGELOG.md",
        "# Changelog\n\n## [1.0.0] - 2026-09-01\n\n- First release.\n",
    )
    write_lf(
        root / "pyproject.toml",
        '[project]\nname = "example"\nversion = "1.0.0"\n\n'
        '[tool.releasing]\nrepository = "foundata/example"\n',
    )
    write_lf(root / ".releasing-notes-v1.0.0", "Keep these existing notes.\n")
    git(root, "init", "-q", "-b", "main")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "project: establish the example")
    git(root, "tag", "-a", "v1.0.0", "-m", "Release 1.0.0")
    return root


@pytest.fixture
def manifest(repository: Path) -> Path:
    directory = repository.parent / "release files"
    directory.mkdir()
    artifact = directory / "example-1.0.0.tar.gz"
    artifact.write_bytes(b"validated distribution bytes")
    recorded = artifacts.build_manifest(
        [artifact],
        repository="foundata/example",
        version="1.0.0",
        source_revision=git(repository, "rev-parse", "HEAD").strip(),
    )
    path = directory / "artifacts.json"
    write_lf(path, artifacts.dump_manifest(recorded))
    shadow = repository / directory.name
    shadow.mkdir()
    (shadow / artifact.name).write_bytes(
        b"wrong distribution from the project directory"
    )
    write_lf(shadow / path.name, "wrong manifest from the project directory")
    return path.relative_to(repository.parent)


def test_create_uses_the_declared_repository_and_the_verified_assets(
    repository: Path, fake_gh: Path, manifest: Path
) -> None:
    before = git(repository, "status", "--porcelain")
    result = release(repository, "--manifest", str(manifest))

    assert result.returncode == 0, result.stderr
    assert captured(result.stdout) == RELEASE_URL + "\n"
    assert b"Created the github release entry for v1.0.0" in result.stderr
    assert b"Attached example-1.0.0.tar.gz" in result.stderr
    call = json.loads(fake_gh.read_text(encoding="utf-8"))
    notes = Path(call["notes_path"])
    directory = repository.parent / manifest.parent
    assert call["arguments"][:10] == [
        "release",
        "create",
        "v1.0.0",
        "--verify-tag",
        "--title",
        "v1.0.0",
        "--repo",
        "github.com/foundata/example",
        "--notes-file",
        str(notes),
    ]
    staged = [Path(value) for value in call["arguments"][10:]]
    assert [path.name for path in staged] == ["artifacts.json", "example-1.0.0.tar.gz"]
    assert all(path.is_absolute() and path.parent != directory for path in staged)
    assert all(not path.parent.exists() for path in staged)
    assert Path(call["cwd"]) == repository
    assert call["notes"] == "- First release.\n"
    assert call["assets"] == {
        "artifacts.json": (directory / "artifacts.json").read_bytes().hex(),
        "example-1.0.0.tar.gz": b"validated distribution bytes".hex(),
    }
    assert not notes.parent.exists()
    assert list((repository.parent / "staged notes").iterdir()) == []
    assert git(repository, "status", "--porcelain") == before
    assert (repository / ".releasing-notes-v1.0.0").read_bytes() == (
        b"Keep these existing notes.\n"
    )


@pytest.mark.parametrize("error", ["remote tag v1.0.0 does not exist", "upload failed"])
def test_a_forge_failure_reports_an_error_and_removes_staged_notes(
    repository: Path,
    fake_gh: Path,
    manifest: Path,
    monkeypatch: pytest.MonkeyPatch,
    error: str,
) -> None:
    monkeypatch.setenv("FAKE_GH_ERROR", error)
    result = release(repository, "--manifest", str(manifest))

    assert result.returncode == 1
    assert result.stdout == b""
    assert error.encode() in result.stderr
    assert b"status 7" in result.stderr
    assert b"Traceback" not in result.stderr
    assert b"Created the" not in result.stderr
    call = json.loads(fake_gh.read_text(encoding="utf-8"))
    assert not Path(call["notes_path"]).parent.exists()
    assert list((repository.parent / "staged notes").iterdir()) == []


def test_dry_run_never_starts_gh_or_stages_notes(
    repository: Path, fake_gh: Path, manifest: Path
) -> None:
    result = release(repository, "--manifest", str(manifest), "--dry-run")

    assert result.returncode == 0, result.stderr
    assert result.stdout == b""
    assert b"--verify-tag" in result.stderr
    assert b"github.com/foundata/example" in result.stderr
    assert not fake_gh.exists()
    assert list((repository.parent / "staged notes").iterdir()) == []


def test_a_missing_local_tag_is_a_cli_error_before_gh_runs(
    repository: Path, fake_gh: Path
) -> None:
    git(repository, "tag", "-d", "v1.0.0")
    result = release(repository)

    assert result.returncode == 1
    assert result.stdout == b""
    assert b"cannot resolve release tag v1.0.0" in result.stderr
    assert b"v1.0.0" in result.stderr
    assert b"Traceback" not in result.stderr
    assert not fake_gh.exists()
    assert list((repository.parent / "staged notes").iterdir()) == []


@POSIX_ONLY
def test_a_manifest_symlink_cannot_upload_a_file_outside_its_directory(
    repository: Path, fake_gh: Path, manifest: Path
) -> None:
    directory = repository.parent / manifest.parent
    artifact = directory / "example-1.0.0.tar.gz"
    external = repository.parent / "outside.tar.gz"
    artifact.rename(external)
    artifact.symlink_to(external)

    result = release(repository, "--manifest", str(manifest))

    assert result.returncode == 1
    assert result.stdout == b""
    assert b"resolves outside the artifact directory" in result.stderr
    assert b"Traceback" not in result.stderr
    assert not fake_gh.exists()
    assert list((repository.parent / "staged notes").iterdir()) == []


@pytest.mark.parametrize(
    "field, value, message",
    [
        ("repository", "other/project", b"manifest records repository other/project"),
        ("sourceRevision", "b" * 40, b"artifacts were built from"),
    ],
)
def test_manifest_provenance_must_match_the_project_and_tag(
    repository: Path,
    fake_gh: Path,
    manifest: Path,
    field: str,
    value: str,
    message: bytes,
) -> None:
    path = repository.parent / manifest
    document = json.loads(path.read_text(encoding="utf-8"))
    document[field] = value
    write_lf(path, json.dumps(document))

    result = release(repository, "--manifest", str(manifest))

    assert result.returncode == 1
    assert result.stdout == b""
    assert message in result.stderr
    assert b"Traceback" not in result.stderr
    assert not fake_gh.exists()


def test_a_minimal_manifest_without_provenance_remains_usable(
    repository: Path, fake_gh: Path, manifest: Path
) -> None:
    path = repository.parent / manifest
    document = json.loads(path.read_text(encoding="utf-8"))
    write_lf(path, json.dumps({"artifacts": document["artifacts"]}))

    result = release(repository, "--manifest", str(manifest))

    assert result.returncode == 0, result.stderr
    assert captured(result.stdout) == RELEASE_URL + "\n"
    assert fake_gh.is_file()


def test_provenance_uses_the_tag_commit_not_a_same_named_branch(
    repository: Path, fake_gh: Path, manifest: Path
) -> None:
    git(repository, "commit", "--allow-empty", "-m", "project: change after release")
    git(repository, "branch", "v1.0.0")

    result = release(repository, "--manifest", str(manifest))

    assert result.returncode == 0, result.stderr
    assert fake_gh.is_file()


def test_notes_ignore_later_commits_and_uncommitted_edits(
    repository: Path, fake_gh: Path
) -> None:
    write_lf(repository / "CHANGELOG.md", "# A different committed changelog\n")
    git(repository, "commit", "-am", "project: replace the changelog after release")
    write_lf(repository / "CHANGELOG.md", "# Uncommitted changes\n")

    result = release(repository)

    assert result.returncode == 0, result.stderr
    assert (
        json.loads(fake_gh.read_text(encoding="utf-8"))["notes"] == "- First release.\n"
    )
    assert (repository / "CHANGELOG.md").read_bytes() == b"# Uncommitted changes\n"


def test_notes_do_not_need_a_working_tree_changelog(
    repository: Path, fake_gh: Path
) -> None:
    (repository / "CHANGELOG.md").unlink()

    result = release(repository)

    assert result.returncode == 0, result.stderr
    assert (
        json.loads(fake_gh.read_text(encoding="utf-8"))["notes"] == "- First release.\n"
    )
    assert not (repository / "CHANGELOG.md").exists()


def test_collection_notes_and_titles_come_from_the_tag(
    repository: Path, fake_gh: Path
) -> None:
    declaration = repository / "pyproject.toml"
    write_lf(
        declaration,
        declaration.read_text(encoding="utf-8") + 'changelog = "antsibull"\n',
    )
    directory = repository / "changelogs"
    directory.mkdir()
    write_lf(
        directory / "changelog.yaml",
        "releases:\n  1.0.0:\n    changes:\n      bugfixes:\n        - Tagged fix\n",
    )
    write_lf(directory / "config.yaml", "sections:\n  - [bugfixes, Tagged fixes]\n")
    git(repository, "add", ".")
    git(repository, "commit", "-m", "collection: record the release")
    git(repository, "tag", "-f", "-a", "v1.0.0", "-m", "Release 1.0.0")
    write_lf(directory / "changelog.yaml", "releases: {}\n")
    write_lf(
        directory / "config.yaml", "sections:\n  - [bugfixes, Uncommitted title]\n"
    )

    result = release(repository)

    assert result.returncode == 0, result.stderr
    assert json.loads(fake_gh.read_text(encoding="utf-8"))["notes"] == (
        "### Tagged fixes\n\n- Tagged fix\n"
    )


def test_working_tree_notes_cannot_replace_a_missing_tagged_changelog(
    repository: Path, fake_gh: Path
) -> None:
    git(repository, "rm", "CHANGELOG.md")
    git(repository, "commit", "-m", "project: remove the changelog")
    git(repository, "tag", "-f", "-a", "v1.0.0", "-m", "Release 1.0.0")
    write_lf(
        repository / "CHANGELOG.md", "# Changelog\n\n## [1.0.0]\n\n- Not committed.\n"
    )

    result = release(repository)

    assert result.returncode == 1
    assert result.stdout == b""
    assert b"cannot read CHANGELOG.md at" in result.stderr
    assert b"Traceback" not in result.stderr
    assert not fake_gh.exists()


def test_gh_reads_private_copies_even_when_the_original_inputs_change(
    repository: Path, fake_gh: Path, manifest: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = repository.parent / manifest
    artifact = path.parent / "example-1.0.0.tar.gz"
    expected = {
        path.name: path.read_bytes().hex(),
        artifact.name: artifact.read_bytes().hex(),
    }
    monkeypatch.setenv("FAKE_GH_MUTATE", json.dumps([str(path), str(artifact)]))

    result = release(repository, "--manifest", str(manifest))

    assert result.returncode == 0, result.stderr
    call = json.loads(fake_gh.read_text(encoding="utf-8"))
    assert call["assets"] == expected
    assert artifact.read_bytes() == b"changed while the uploader runs"
    assert list((repository.parent / "staged notes").iterdir()) == []
