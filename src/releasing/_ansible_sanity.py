# SPDX-FileCopyrightText: foundata GmbH <https://foundata.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Run a collection's sanity sessions on an isolated, complete release commit."""

import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from packaging.version import Version

from releasing import __version__, processes, reporting
from releasing._source_export import BuildError

SANITY_TIMEOUT = 7200.0
ENVIRONMENT = {
    "CI": "true",
    "ANTSIBULL_CHANGE_DETECTION": "false",
    "NOXSESSION": "",
    "PYTHONPATH": "",
}


@dataclass(frozen=True)
class Result:
    """Successful concrete sessions and the tools that ran them."""

    sessions: tuple[str, ...]
    tools: dict[str, str]


def run(root: Path, revision: str, workspace: Path, *, dry_run: bool) -> Result | None:
    """Check the selected commit; retain logs on failure and never edit its source."""
    if dry_run:
        reporting.command(
            [
                "uv",
                "run",
                "--quiet",
                "--no-project",
                "--script",
                "noxfile.py",
                "-s",
                "ansible-test-sanity",
                "--error-on-missing-interpreters",
                "--report",
                "<sanity report>",
            ],
            cwd=workspace / "sanity-source",
            executed=False,
        )
        return None
    diagnostics = Path(tempfile.mkdtemp(prefix="releasing-sanity-"))
    try:
        result = _run(root, revision, workspace / "sanity-source", diagnostics)
    except (OSError, ValueError, processes.ProcessError, BuildError) as exc:
        (diagnostics / "failure.txt").write_text(str(exc) + "\n", encoding="utf-8")
        raise BuildError(
            f"Ansible sanity failed for {revision}; diagnostics: {diagnostics}\n{exc}"
        ) from exc
    shutil.rmtree(diagnostics)
    return result


def _run(root: Path, revision: str, source: Path, diagnostics: Path) -> Result:
    # A clone retains export-ignored tests without registering a worktree in
    # the developer's repository. Disable checkout hooks and host EOL rewriting.
    processes.git(
        root, "clone", "--shared", "--no-checkout", "--", str(root), str(source)
    )
    processes.git(
        source,
        "-c",
        f"core.hooksPath={diagnostics}",
        "-c",
        "core.autocrlf=false",
        "-c",
        "core.eol=lf",
        "checkout",
        "--detach",
        revision,
    )
    if not (source / "noxfile.py").is_file():
        raise BuildError("the release commit needs noxfile.py with ansible-test-sanity")
    uv = str(processes.executable("uv"))
    command = [uv, "run", "--quiet", "--no-project", "--script", "noxfile.py"]
    nox_version = diagnostics / "nox-version.txt"
    processes.run(
        [*command, "--version"], cwd=source, environment=ENVIRONMENT, log=nox_version
    )
    tools = {
        "releasing": __version__,
        "uv": processes.run([uv, "--version"]).strip(),
        "nox": str(Version(nox_version.read_text(encoding="utf-8").strip())),
    }
    listing = processes.run(
        [*command, "-s", "ansible-test-sanity", "--list", "--json"],
        cwd=source,
        environment=ENVIRONMENT,
    )
    (diagnostics / "sessions.json").write_text(listing, encoding="utf-8")
    sessions = _sessions(listing)
    report = diagnostics / "report.json"
    reporting.phase(f"Running {len(sessions)} sanity sessions on {revision[:12]}")
    reporting.phase(f"Running with sanity output in {diagnostics / 'sanity.log'}")
    processes.run(
        [
            *command,
            "-s",
            "ansible-test-sanity",
            "--error-on-missing-interpreters",
            "--report",
            str(report),
        ],
        cwd=source,
        environment=ENVIRONMENT,
        timeout=SANITY_TIMEOUT,
        log=diagnostics / "sanity.log",
        echo=True,
    )
    _check_report(report.read_text(encoding="utf-8"), sessions)
    if (
        processes.git(source, "rev-parse", "HEAD").strip() != revision
        or processes.git(
            source, "status", "--porcelain", "--untracked-files=no"
        ).strip()
    ):
        raise BuildError("sanity changed the tested commit or tracked files")
    return Result(sessions, tools)


def _sessions(text: str) -> tuple[str, ...]:
    data = json.loads(text)
    if not isinstance(data, list):
        raise BuildError("Nox session discovery did not return a list")
    names = [entry.get("session") for entry in data if isinstance(entry, dict)]
    sessions = tuple(
        name
        for name in names
        if isinstance(name, str) and name.startswith("ansible-test-sanity-")
    )
    if not sessions or len(set(sessions)) != len(sessions):
        raise BuildError(
            "Nox must select distinct concrete ansible-test-sanity-* sessions"
        )
    return sessions


def _check_report(text: str, expected: tuple[str, ...]) -> None:
    data = json.loads(text)
    entries = data.get("sessions") if isinstance(data, dict) else None
    if not isinstance(entries, list) or not entries or data.get("result") != 1:
        raise BuildError("Nox did not report a successful sanity run")
    names = []
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("result") != "success":
            raise BuildError(
                "every selected sanity session must succeed; skips are refused"
            )
        name = entry.get("name")
        if not isinstance(name, str) or name in names:
            raise BuildError("Nox reported invalid or duplicate sessions")
        names.append(name)
    if set(names) != {*expected, "ansible-test-sanity"}:
        raise BuildError("Nox results do not match the selected sanity sessions")
