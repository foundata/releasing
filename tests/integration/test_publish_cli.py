# SPDX-FileCopyrightText: foundata GmbH <https://foundata.com>
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from releasing.artifacts import build_manifest, dump_manifest
from tests.support import with_sanity, write_lf

pytestmark = pytest.mark.integration


def test_partial_upload_reports_recovery_details_and_cleans_staging(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project checkout"
    root.mkdir()
    write_lf(root / "README.md", "# Example\n")
    write_lf(root / "CHANGELOG.md", "# Changelog\n")
    write_lf(
        root / "pyproject.toml",
        '[project]\nname = "example"\nversion = "1.0.0"\n'
        '[tool.releasing]\nrepository = "foundata/example"\nindex = "galaxy"\n',
    )
    directory = tmp_path / "release files"
    directory.mkdir()
    files = [
        directory / f"foundata-{name}-1.0.0.tar.gz"
        for name in ("alpha", "beta", "gamma")
    ]
    for path in files:
        path.write_bytes(b"validated collection")
    manifest = directory / "artifacts.json"
    write_lf(
        manifest,
        dump_manifest(
            with_sanity(
                build_manifest(
                    files,
                    repository="foundata/example",
                    version="1.0.0",
                    source_revision=None,
                )
            )
        ),
    )
    programs = tmp_path / "programs"
    programs.mkdir()
    script = programs / "galaxy.py"
    write_lf(
        script,
        """import json
import os
import sys
from pathlib import Path

assert sys.argv[1:3] == ["collection", "publish"]
path = Path(sys.argv[3])
assert path.read_bytes() == b"validated collection"
with Path(os.environ["UPLOAD_CALLS"]).open("a", encoding="utf-8") as stream:
    stream.write(json.dumps(str(path)) + "\\n")
if "beta" in path.name:
    print("connection lost", file=sys.stderr)
    sys.exit(7)
""",
    )
    if sys.platform == "win32":
        write_lf(
            programs / "ansible-galaxy.cmd",
            f'@echo off\n"{sys.executable}" -I "{script}" %*\n',
        )
    else:
        executable = programs / "ansible-galaxy"
        write_lf(
            executable,
            f'#!/bin/sh\nexec {shlex.quote(sys.executable)} -I {shlex.quote(str(script))} "$@"\n',
        )
        executable.chmod(0o755)
    calls = tmp_path / "calls.jsonl"
    staging = tmp_path / "staging"
    staging.mkdir()
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-m",
            "releasing",
            "publish",
            str(manifest),
            "--project",
            str(root),
        ],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": str(programs),
            "UPLOAD_CALLS": str(calls),
            "TMPDIR": str(staging),
            "TMP": str(staging),
            "TEMP": str(staging),
        },
        capture_output=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 1
    assert result.stdout == b""
    assert b"Confirmed by the upload tool: foundata-alpha-1.0.0.tar.gz" in result.stderr
    assert b"Outcome unconfirmed: foundata-beta-1.0.0.tar.gz" in result.stderr
    assert b"Not attempted: foundata-gamma-1.0.0.tar.gz" in result.stderr
    assert b"Check the index before retrying" in result.stderr
    assert b"Traceback" not in result.stderr
    uploaded = [
        Path(json.loads(line))
        for line in calls.read_text(encoding="utf-8").splitlines()
    ]
    assert [path.name for path in uploaded] == [files[0].name, files[1].name]
    assert all(
        path.parent != directory and not path.parent.exists() for path in uploaded
    )
    assert list(staging.iterdir()) == []
    assert all(path.read_bytes() == b"validated collection" for path in files)
