# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def release(cwd: Path, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-I", "-m", "releasing", "artifacts", *arguments],
        cwd=cwd,
        env={**os.environ, "PATH": str(cwd / "no-programs")},
        capture_output=True,
        timeout=60,
        check=False,
    )


@pytest.fixture
def built(tmp_path: Path) -> Path:
    if shutil.which("uv") is None:
        pytest.skip("uv is required to build the sample project")
    project = tmp_path / "project"
    (project / "src" / "sample").mkdir(parents=True)
    (project / "src" / "sample" / "__init__.py").write_text(
        '"""Sample."""\n', encoding="utf-8"
    )
    (project / "README.md").write_text(
        "# Sample\n\nSee [the guide](./docs/guide.md).\n", encoding="utf-8"
    )
    (project / "pyproject.toml").write_text(
        '[project]\nname = "sample"\nversion = "0.1.0"\n'
        'readme = "README.md"\n\n'
        '[build-system]\nrequires = ["uv_build>=0.12.3,<0.13.0"]\nbuild-backend = "uv_build"\n',
        encoding="utf-8",
    )
    subprocess.run(
        ["uv", "build", "--out-dir", str(tmp_path / "dist"), str(project)],
        check=True,
        capture_output=True,
        timeout=600,
    )
    return tmp_path / "dist"


def test_check_reports_relative_links_in_real_distributions(built: Path) -> None:
    files = sorted(str(path) for path in built.iterdir() if path.name != ".gitignore")
    result = release(built, "check", "--version", "0.1.0", *files)
    assert result.returncode == 1
    assert result.stderr.count(b"relative destination") == 2
    assert b"'./docs/guide.md'" in result.stderr
    assert b"Traceback" not in result.stderr
    result = release(built, "check", "--version", "0.2.0", *files)
    assert b"metadata version 0.1.0 != 0.2.0" in result.stderr


def test_manifest_and_verify_round_trip(tmp_path: Path) -> None:
    import io
    import tarfile

    path = tmp_path / "example-1.0.0.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        data = b"Name: example\nVersion: 1.0.0\n\n# Example\n\n[x](https://example.test/)\n"
        info = tarfile.TarInfo("example-1.0.0/PKG-INFO")
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))
    manifest = tmp_path / "artifacts.json"
    result = release(
        tmp_path,
        "manifest",
        "--version",
        "1.0.0",
        "--out",
        str(manifest),
        "--revision",
        "b" * 40,
        str(path),
    )
    assert result.returncode == 0, result.stderr
    verified = release(tmp_path, "verify", str(manifest))
    assert verified.stdout == b""
    assert b"1 artifact(s) match the manifest" in verified.stderr
    path.write_bytes(path.read_bytes() + b"\0")
    result = release(tmp_path, "verify", str(manifest))
    assert result.returncode == 1
    assert b"SHA-256 differs" in result.stderr
    assert (
        release(
            tmp_path,
            "manifest",
            "--version",
            "1.0.0",
            "--out",
            str(manifest),
            str(path),
        ).returncode
        == 1
    )
