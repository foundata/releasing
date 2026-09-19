# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded execution of the few external programs the release steps drive.

Every call names its executable explicitly, passes no shell, has a timeout and
reports failures with the program's own diagnostics. Secrets are never passed
as arguments: a token reaches a child through the environment only.
"""

import os
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

TIMEOUT = 600.0


class ProcessError(RuntimeError):
    """An external program was missing, failed or timed out."""


def executable(name: str) -> Path:
    """Locate a required program in the search path."""
    found = shutil.which(name)
    if found is None:
        raise ProcessError(f"required program not found in PATH: {name}")
    return Path(found)


def run(
    argv: Sequence[str],
    *,
    cwd: Path | None = None,
    timeout: float = TIMEOUT,
    environment: Mapping[str, str] | None = None,
    stdout: Path | None = None,
) -> str:
    """Run one program and return its standard output.

    ``environment`` adds variables to a copy of the current environment; use it
    for credentials. ``stdout`` writes the output to a file instead of
    capturing it, for archives and other binary output.
    """
    values = None if environment is None else {**os.environ, **environment}
    try:
        if stdout is not None:
            with stdout.open("wb") as stream:
                subprocess.run(
                    list(argv),
                    cwd=cwd,
                    env=values,
                    stdout=stream,
                    stderr=subprocess.PIPE,
                    timeout=timeout,
                    check=True,
                )
            return ""
        result = subprocess.run(
            list(argv),
            cwd=cwd,
            env=values,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        if isinstance(detail, bytes):
            detail = detail.decode("utf-8", errors="replace").strip()
        raise ProcessError(
            f"{argv[0]} failed with status {exc.returncode}"
            + (f":\n{detail}" if detail else "")
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise ProcessError(f"{argv[0]} timed out after {timeout:.0f}s") from exc
    except OSError as exc:
        raise ProcessError(f"cannot run {argv[0]}: {exc}") from exc
    return result.stdout


def git(
    root: Path, *arguments: str, timeout: float = TIMEOUT, stdout: Path | None = None
) -> str:
    """Run a Git command in ``root`` with the caller's configuration untouched."""
    return run(
        [str(executable("git")), "-C", str(root), *arguments],
        timeout=timeout,
        stdout=stdout,
    )


def is_checkout(root: Path) -> bool:
    """Whether ``root`` is inside a Git working tree, without invoking Git."""
    current = root.resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return True
    return False
