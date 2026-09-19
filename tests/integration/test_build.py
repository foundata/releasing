# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

from releasing.artifacts import load_manifest, sha256_file

pytestmark = pytest.mark.integration
GIT_ENV = {
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
}
README = """# Sample

See the [development guide](./DEVELOPMENT.md) and the
![logo](assets/logo.svg) it ships.

[![badge](https://img.example/b.svg)](https://example.test/)
"""
CHANGELOG = """# Changelog

## [Unreleased]

- Nothing worth mentioning right now.


## [1.0.0] - 2026-09-01

- All functionality.


[unreleased]: https://github.com/foundata/sample/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/foundata/sample/releases/tag/v1.0.0
"""
PYPROJECT = """[project]
name = "sample"
version = "1.0.0"
description = "A sample project."
readme = "README.md"
requires-python = ">=3.11"

[build-system]
requires = ["uv_build>=0.12.3,<0.13.0"]
build-backend = "uv_build"

[tool.releasing]
repository = "foundata/sample"
version-files = ["pyproject.toml", "src/sample/__init__.py"]
"""


def git(cwd: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *arguments],
        env={**os.environ, **GIT_ENV},
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    ).stdout


def release(cwd: Path, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-I", "-m", "releasing", *arguments],
        cwd=cwd,
        env={**os.environ, **GIT_ENV},
        capture_output=True,
        timeout=900,
        check=False,
    )


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    if shutil.which("uv") is None:
        pytest.skip("uv is required to build distributions")
    root = tmp_path / "sample"
    (root / "src" / "sample").mkdir(parents=True)
    (root / "assets").mkdir()
    (root / "src" / "sample" / "__init__.py").write_text(
        '"""Sample."""\n\n__version__ = "1.0.0"\n', encoding="utf-8"
    )
    (root / "assets" / "logo.svg").write_text("<svg></svg>\n", encoding="utf-8")
    (root / "README.md").write_text(README, encoding="utf-8")
    (root / "DEVELOPMENT.md").write_text("# Development\n", encoding="utf-8")
    (root / "CHANGELOG.md").write_text(CHANGELOG, encoding="utf-8")
    (root / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    (root / "notes.txt").write_text("private\n", encoding="utf-8")
    (root / ".gitattributes").write_text("notes.txt export-ignore\n", encoding="utf-8")
    git(root.parent, "init", "-q", "-b", "main", str(root))
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "project: establish the sample")
    return root


def test_build_prepares_the_readme_inside_the_export_only(repository: Path) -> None:
    out = repository.parent / "dist"
    result = release(repository, "build", "--out", str(out), "--expect", "1.0.0")
    assert result.returncode == 0, result.stderr
    assert b"prepared: README.md" in result.stderr

    # The committed README keeps its relative links; nothing was restored.
    assert (repository / "README.md").read_text(encoding="utf-8") == README
    assert git(repository, "status", "--porcelain") == ""

    wheel = out / "sample-1.0.0-py3-none-any.whl"
    sdist = out / "sample-1.0.0.tar.gz"
    assert sorted(path.name for path in out.iterdir()) == sorted(
        ["artifacts.json", sdist.name, wheel.name]
    )
    with zipfile.ZipFile(wheel) as archive:
        metadata = next(
            name for name in archive.namelist() if name.endswith("METADATA")
        )
        description = archive.read(metadata).decode()
    assert (
        "https://github.com/foundata/sample/blob/refs/tags/v1.0.0/DEVELOPMENT.md"
        in description
    )
    assert (
        "https://raw.githubusercontent.com/foundata/sample/refs/tags/v1.0.0/assets/logo.svg"
        in description
    )
    assert "](./" not in description

    # export-ignore keeps a tracked file out of the artifacts.
    with tarfile.open(sdist) as archive:
        assert not any(name.endswith("notes.txt") for name in archive.getnames())


def test_build_records_a_manifest_of_exactly_the_built_files(repository: Path) -> None:
    out = repository.parent / "dist"
    assert release(repository, "build", "--out", str(out)).returncode == 0
    manifest = load_manifest(out / "artifacts.json")
    assert manifest.version == "1.0.0"
    assert manifest.repository == "foundata/sample"
    assert manifest.source_revision == git(repository, "rev-parse", "HEAD").strip()
    assert {entry.filename for entry in manifest.artifacts} == {
        "sample-1.0.0.tar.gz",
        "sample-1.0.0-py3-none-any.whl",
    }
    for entry in manifest.artifacts:
        assert sha256_file(out / entry.filename) == entry.sha256
    assert (
        release(
            repository, "artifacts", "verify", str(out / "artifacts.json")
        ).returncode
        == 0
    )


def test_build_uses_the_committed_revision_not_the_working_tree(
    repository: Path,
) -> None:
    (repository / "src" / "sample" / "__init__.py").write_text(
        '"""Sample."""\n\n__version__ = "9.9.9"\n', encoding="utf-8"
    )
    (repository / "uncommitted.txt").write_text("litter\n", encoding="utf-8")
    out = repository.parent / "dist"
    result = release(repository, "build", "--out", str(out))
    assert result.returncode == 0, result.stderr
    assert (out / "sample-1.0.0.tar.gz").is_file()
    with tarfile.open(out / "sample-1.0.0.tar.gz") as archive:
        assert not any("uncommitted" in name for name in archive.getnames())


def test_build_refuses_an_existing_output_and_a_wrong_expectation(
    repository: Path,
) -> None:
    out = repository.parent / "dist"
    out.mkdir()
    result = release(repository, "build", "--out", str(out))
    assert result.returncode == 1
    assert b"must not already exist" in result.stderr
    result = release(
        repository, "build", "--out", str(repository.parent / "d2"), "--expect", "2.0.0"
    )
    assert result.returncode == 1
    assert b"expected 2.0.0, sites state 1.0.0" in result.stderr
    assert not (repository.parent / "d2").exists()


def test_build_stops_on_a_broken_link_and_a_stale_changelog(repository: Path) -> None:
    (repository / "README.md").write_text(
        README + "\nA [missing file](./absent.md).\n", encoding="utf-8"
    )
    git(repository, "commit", "-qam", "repository: link a missing file")
    result = release(repository, "build", "--out", str(repository.parent / "d1"))
    assert result.returncode == 1
    assert b"local target does not exist" in result.stderr
    assert b"Traceback" not in result.stderr

    git(repository, "revert", "--no-edit", "HEAD")
    (repository / "src" / "sample" / "__init__.py").write_text(
        '"""Sample."""\n\n__version__ = "1.1.0"\n', encoding="utf-8"
    )
    (repository / "pyproject.toml").write_text(
        PYPROJECT.replace('version = "1.0.0"', 'version = "1.1.0"'), encoding="utf-8"
    )
    git(repository, "commit", "-qam", "release: prepare 1.1.0")
    result = release(repository, "build", "--out", str(repository.parent / "d2"))
    assert result.returncode == 1
    assert b"latest released section must be [1.1.0]" in result.stderr


def test_build_refuses_a_local_dependency_source(repository: Path) -> None:
    (repository / "pyproject.toml").write_text(
        PYPROJECT
        + '\n[tool.uv.sources]\nhelper = { path = "/home/someone/dev/helper" }\n',
        encoding="utf-8",
    )
    git(repository, "commit", "-qam", "dependencies: resolve the helper locally")
    out = repository.parent / "dist"
    result = release(repository, "build", "--out", str(out))
    assert result.returncode == 1
    assert b"publish a path from this machine" in result.stderr
    assert b"helper = /home/someone/dev/helper" in result.stderr
    assert not out.exists()

    # The escape exists for a throwaway build and says so on every run.
    result = release(repository, "build", "--out", str(out), "--allow-local-sources")
    assert result.returncode == 0, result.stderr
    assert b"WARNING: built with a local dependency source" in result.stderr
    assert b"must never be uploaded" in result.stderr
    assert (out / "sample-1.0.0.tar.gz").is_file()


def test_workspace_sources_are_not_local_paths(repository: Path) -> None:
    (repository / "pyproject.toml").write_text(
        PYPROJECT + "\n[tool.uv.sources]\nmember = { workspace = true }\n",
        encoding="utf-8",
    )
    git(
        repository, "commit", "-qam", "dependencies: take the member from the workspace"
    )
    result = release(repository, "build", "--out", str(repository.parent / "dist"))
    assert result.returncode == 0, result.stderr


WORKSPACE_ROOT = """[tool.uv.workspace]
members = ["packages/*"]

[tool.releasing]
repository = "foundata/product"
version-files = [
  "packages/engine/pyproject.toml",
  "packages/frontend/pyproject.toml",
]
dependency-pins = [
  { file = "packages/frontend/pyproject.toml", name = "engine" },
]

[[tool.releasing.readmes]]
copies = ["packages/engine/README.md", "packages/frontend/README.md"]
"""
MEMBER = """[project]
name = "{name}"
version = "1.0.0"
description = "A workspace member."
readme = "README.md"
requires-python = ">=3.11"
dependencies = [{dependencies}]

[build-system]
requires = ["uv_build>=0.12.3,<0.13.0"]
build-backend = "uv_build"
"""


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    if shutil.which("uv") is None:
        pytest.skip("uv is required to build distributions")
    root = tmp_path / "product"
    root.mkdir()
    (root / "README.md").write_text(README, encoding="utf-8")
    (root / "DEVELOPMENT.md").write_text("# Development\n", encoding="utf-8")
    (root / "CHANGELOG.md").write_text(
        CHANGELOG.replace("foundata/sample", "foundata/product"), encoding="utf-8"
    )
    (root / "assets").mkdir()
    (root / "assets" / "logo.svg").write_text("<svg></svg>\n", encoding="utf-8")
    (root / "pyproject.toml").write_text(WORKSPACE_ROOT, encoding="utf-8")
    for name, dependencies in (("engine", ""), ("frontend", '"engine>=1.0.0,<2"')):
        package = root / "packages" / name
        (package / "src" / name).mkdir(parents=True)
        (package / "src" / name / "__init__.py").write_text(
            '"""Member."""\n', encoding="utf-8"
        )
        (package / "README.md").write_text(
            f"# {name}\n\nA pointer.\n", encoding="utf-8"
        )
        (package / "pyproject.toml").write_text(
            MEMBER.format(name=name, dependencies=dependencies), encoding="utf-8"
        )
    git(root.parent, "init", "-q", "-b", "main", str(root))
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "project: establish the product")
    return root


def test_build_produces_every_workspace_member(workspace: Path) -> None:
    out = workspace.parent / "dist"
    result = release(workspace, "build", "--out", str(out), "--expect", "1.0.0")
    assert result.returncode == 0, result.stderr
    assert sorted(path.name for path in out.iterdir()) == sorted(
        [
            "artifacts.json",
            "engine-1.0.0-py3-none-any.whl",
            "engine-1.0.0.tar.gz",
            "frontend-1.0.0-py3-none-any.whl",
            "frontend-1.0.0.tar.gz",
        ]
    )
    # The prepared project README replaced both members' pointer READMEs, so
    # each package index page shows the full project page.
    with zipfile.ZipFile(out / "frontend-1.0.0-py3-none-any.whl") as archive:
        metadata = next(n for n in archive.namelist() if n.endswith("METADATA"))
        description = archive.read(metadata).decode()
    assert "A pointer." not in description
    assert (
        "https://github.com/foundata/product/blob/refs/tags/v1.0.0/DEVELOPMENT.md"
        in description
    )
