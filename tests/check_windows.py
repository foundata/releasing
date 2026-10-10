# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later
"""Check native Windows behavior and the installed wheel without a POSIX shell."""

import argparse
import os
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(command: Sequence[str], cwd: Path) -> None:
    environment = {**os.environ, "UV_LINK_MODE": "copy"}
    for name in ("PYTHONPATH", "PYTHONHOME"):
        environment.pop(name, None)
    print("$ " + subprocess.list2cmdline(command), flush=True)
    subprocess.run(command, cwd=cwd, env=environment, timeout=1800, check=True)


def check(root: Path, python: str) -> None:
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    ).stdout
    if status.strip():
        raise ValueError("tracked files differ from HEAD; commit or stash first")
    run(["git", "diff", "--check"], root)
    uv = ["uv", "run", "--locked", "--isolated", "--python", python]
    for arguments in (
        ["release", "config", "check"],
        ["release", "version", "check"],
        ["release", "changelog", "check"],
        ["ruff", "format", "--check", "."],
        ["ruff", "check", "."],
        ["mypy"],
        ["python", "tests/check_markdown.py"],
        ["pytest", "-q"],
    ):
        run([*uv, *arguments], root)
    declared = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]["version"]
    with tempfile.TemporaryDirectory(prefix="releasing-windows-check-") as value:
        work = Path(value)
        dist = work / "dist"
        run([*uv, "release", "build", "--out", str(dist)], root)
        wheels = list(dist.glob("*.whl"))
        sources = list(dist.glob("*.tar.gz"))
        if len(wheels) != 1 or len(sources) != 1:
            raise ValueError("expected exactly one built wheel and source distribution")
        environment = work / "installed"
        run(["uv", "venv", "--python", python, str(environment)], work)
        executable = str(environment / "Scripts" / "python.exe")
        command = str(environment / "Scripts" / "release.exe")
        run(["uv", "pip", "install", "--python", executable, str(wheels[0])], work)
        run(
            [
                executable,
                "-I",
                "-c",
                "import sys, releasing; assert releasing.__version__ == sys.argv[1]",
                declared,
            ],
            work,
        )
        run([command, "--help"], work)
        run([command, "config", "--help"], work)
        run(
            [
                executable,
                "-I",
                str(root / "tests" / "smoke_installed.py"),
                command,
                declared,
                str(wheels[0]),
                str(sources[0]),
            ],
            work,
        )


def main(
    arguments: Sequence[str] | None = None, *, platform: str = sys.platform
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", default="3.14")
    args = parser.parse_args(arguments)
    if platform != "win32":
        print(
            "This check requires native Windows, not WSL or another host OS.",
            file=sys.stderr,
        )
        return 2
    try:
        check(ROOT, args.python)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"Windows check failed: {exc}", file=sys.stderr)
        return 1
    print("All native Windows checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
