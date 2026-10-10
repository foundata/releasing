# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from releasing import artifacts
from tests.support import captured, write_lf

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
    assert call["arguments"] == [
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
        str(directory / "artifacts.json"),
        str(directory / "example-1.0.0.tar.gz"),
    ]
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
    assert b"cannot read the commits to check" in result.stderr
    assert b"v1.0.0" in result.stderr
    assert b"Traceback" not in result.stderr
    assert not fake_gh.exists()
    assert list((repository.parent / "staged notes").iterdir()) == []
