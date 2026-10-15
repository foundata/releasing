# SPDX-FileCopyrightText: foundata GmbH <https://foundata.com>
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import shlex
import sys
import tempfile
from pathlib import Path

import pytest

from releasing import _ansible_sanity, artifacts, build, processes, publish
from tests.integration.test_build import git
from tests.support import write_lf
from tests.unit.test_artifacts import collection

pytestmark = pytest.mark.integration

UV = """import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
if args == ["--version"]:
    print("uv fixture")
    raise SystemExit(0)
assert args[:5] == ["run", "--quiet", "--no-project", "--script", "noxfile.py"]
assert os.environ["CI"] == "true"
assert os.environ["ANTSIBULL_CHANGE_DETECTION"] == "false"
assert Path("tests/kept.txt").read_text() == "committed"
assert Path("README.md").read_text() == "# Linux\\n\\n[guide](guide.md)\\n"
assert not Path("untracked.txt").exists()
assert Path.cwd() != Path(os.environ["ORIGINAL_CHECKOUT"])
if "--version" in args:
    print("2026.8.17", file=sys.stderr)
    raise SystemExit(0)
mode = os.environ.get("SANITY_MODE", "success")
names = ["ansible-test-sanity", "ansible-test-sanity-2.19"]
if "--list" in args:
    print(json.dumps([{"session": n} for n in names]))
    raise SystemExit(0)
print("sanity stdout", flush=True)
print("sanity stderr", file=sys.stderr, flush=True)
if mode == "fail":
    raise SystemExit(7)
if mode == "timeout":
    import time
    time.sleep(60)
if mode == "modify":
    Path("README.md").write_text("rewritten")
if mode == "missing-report":
    raise SystemExit(0)
result = "skipped" if mode == "skip" else "success"
Path(args[args.index("--report") + 1]).write_text(json.dumps({
    "result": 1, "sessions": [{"name": n, "result": result} for n in names]
}))
"""


@pytest.fixture
def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "collection"
    (root / "tests").mkdir(parents=True)
    (root / "changelogs").mkdir()
    write_lf(root / "README.md", "# Linux\n\n[guide](guide.md)\n")
    write_lf(root / "guide.md", "# Guide\n")
    write_lf(root / "tests/kept.txt", "committed")
    write_lf(root / "noxfile.py", "# fixture runner\n")
    write_lf(root / ".gitattributes", "tests export-ignore\nnoxfile.py export-ignore\n")
    write_lf(
        root / "galaxy.yml", 'namespace: foundata\nname: linux\nversion: "1.4.0"\n'
    )
    write_lf(
        root / "changelogs/changelog.yaml",
        "releases:\n  1.4.0:\n    changes:\n      bugfixes: [Fixed]\n",
    )
    write_lf(
        root / "releasing.toml",
        'repository = "foundata/linux"\necosystem = "ansible-collection"\n',
    )
    git(tmp_path, "init", "-q", "-b", "main", str(root))
    git(root, "add", ".")
    git(root, "commit", "-qm", "collection: establish fixture")
    programs = tmp_path / "programs"
    programs.mkdir()
    script = programs / "uv.py"
    write_lf(script, UV)
    if sys.platform == "win32":
        write_lf(
            programs / "uv.cmd", f'@echo off\n"{sys.executable}" -I "{script}" %*\n'
        )
    else:
        wrapper = programs / "uv"
        write_lf(
            wrapper,
            f'#!/bin/sh\nexec {shlex.quote(sys.executable)} -I {shlex.quote(str(script))} "$@"\n',
        )
        wrapper.chmod(0o755)
    monkeypatch.setenv("PATH", str(programs) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("ORIGINAL_CHECKOUT", str(root))
    monkeypatch.setenv("ANTSIBULL_CHANGE_DETECTION", "true")
    return root


def pack(exported: Path, staged: Path, *, dry_run: bool = False) -> list[Path]:
    assert not (exported / "tests").exists()
    if dry_run:
        return []
    return [collection(staged, readme=(exported / "README.md").read_text())]


def test_build_checks_requested_commit_and_binds_artifacts(
    repository: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    revision = git(repository, "rev-parse", "HEAD").strip()
    write_lf(repository / "tests/kept.txt", "later commit")
    git(repository, "commit", "-qam", "tests: change later revision")
    write_lf(repository / "README.md", "uncommitted")
    write_lf(repository / "untracked.txt", "untracked")
    before = git(repository, "status", "--porcelain")
    monkeypatch.setattr(build, "_build_collection", pack)
    result = build.build(repository, revision=revision, out=repository.parent / "dist")
    manifest = artifacts.load_manifest(result.manifest)
    assert manifest.source_revision == revision
    assert manifest.ansible_sanity is not None
    assert manifest.ansible_sanity.sessions == ("ansible-test-sanity-2.19",)
    assert manifest.ansible_sanity.tools["uv"] == "uv fixture"
    assert manifest.ansible_sanity.tools["nox"] == "2026.8.17"
    assert publish.plan(manifest, result.directory, index="galaxy").files
    assert git(repository, "status", "--porcelain") == before
    assert (repository / "README.md").read_text() == "uncommitted"


@pytest.mark.parametrize(
    "mode", ["fail", "skip", "modify", "missing-report", "timeout"]
)
def test_failed_gate_stops_before_build_and_keeps_logs(
    repository: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    monkeypatch.setenv("SANITY_MODE", mode)
    if mode == "timeout":
        monkeypatch.setattr(_ansible_sanity, "SANITY_TIMEOUT", 1)
    diagnostics = repository.parent / "diagnostics"
    diagnostics.mkdir()
    original = tempfile.mkdtemp

    def mkdtemp(
        suffix: str | None = None,
        prefix: str | None = None,
        dir: str | None = None,  # noqa: A002 - match tempfile.mkdtemp's API
    ) -> str:
        if prefix == "releasing-sanity-":
            return str(diagnostics)
        return original(suffix=suffix, prefix=prefix, dir=dir)

    monkeypatch.setattr(tempfile, "mkdtemp", mkdtemp)

    def refuse(*args: object, **kwargs: object) -> list[Path]:
        pytest.fail("a failed sanity gate must not build")

    monkeypatch.setattr(build, "_build_collection", refuse)
    out = repository.parent / "dist"
    with pytest.raises(build.BuildError, match="Ansible sanity failed"):
        build.build(repository, out=out)
    assert not out.exists()
    assert (diagnostics / "failure.txt").is_file()
    log = (diagnostics / "sanity.log").read_text()
    assert "sanity stdout" in log and "sanity stderr" in log


def test_dry_run_never_invokes_sanity_or_creates_evidence(
    repository: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SANITY_MODE", "fail")
    monkeypatch.setattr(build, "_build_collection", pack)
    real = processes.run

    def run(argv: list[str], **kwargs: object) -> str:
        assert Path(argv[0]).stem != "uv", "dry-run must not run Nox or uv"
        return real(argv, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(processes, "run", run)
    out = repository.parent / "dist"
    result = build.build(repository, out=out, dry_run=True)
    assert result.files == () and not out.exists()


def test_missing_noxfile_is_a_build_failure(
    repository: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    git(repository, "rm", "noxfile.py")
    git(repository, "commit", "-qm", "tests: remove runner")
    with pytest.raises(build.BuildError, match=r"needs noxfile\.py"):
        build.build(repository, out=repository.parent / "dist")


def test_missing_uv_stops_before_build(
    repository: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = processes.executable

    def executable(name: str) -> Path:
        if name == "uv":
            raise processes.ProcessError("required program not found in PATH: uv")
        return original(name)

    monkeypatch.setattr(processes, "executable", executable)
    out = repository.parent / "dist"
    with pytest.raises(build.BuildError, match="required program not found"):
        build.build(repository, out=out)
    assert not out.exists()
