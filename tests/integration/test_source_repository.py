# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later
"""A source repository is released as its tag: no version site and no index."""

import os
import subprocess
from pathlib import Path

import pytest

from releasing import cli, forge_api, verify
from tests.support import write_lf

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
CHANGELOG = """# Changelog

## [Unreleased]

- Nothing worth mentioning right now.


## [2.7.0] - 2026-09-25

- Release validation.


## [2.6.2] - 2026-08-28

- Fixes.


[unreleased]: https://github.com/foundata/skeletons/compare/v2.7.0...HEAD
[2.7.0]: https://github.com/foundata/skeletons/releases/tag/v2.7.0
[2.6.2]: https://github.com/foundata/skeletons/releases/tag/v2.6.2
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


@pytest.fixture
def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for name, value in GIT_ENV.items():
        monkeypatch.setenv(name, value)
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", str(remote))
    root = tmp_path / "skeletons"
    root.mkdir()
    write_lf(root / "README.md", "# Skeletons\n")
    write_lf(root / "CHANGELOG.md", CHANGELOG)
    write_lf(
        root / ".releasing.toml",
        'repository = "foundata/skeletons"\necosystem = "source-repository"\n',
    )
    # The development toolchain's own pyproject: its version is not the
    # project's and must never be read as one.
    write_lf(
        root / "pyproject.toml",
        '[project]\nname = "skeletons-development"\nversion = "0.0.0"\n',
    )
    git(tmp_path, "init", "-q", "-b", "main", str(root))
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "project: establish the skeletons")
    git(root, "remote", "add", "origin", str(remote))
    git(root, "push", "-q", "-u", "origin", "main")
    return root


def run(repository: Path, *arguments: str) -> int:
    return cli.main([*arguments, "--project", str(repository)])


def test_the_version_is_the_changelogs_latest_release(
    repository: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(repository, "version", "check") == 0
    assert capsys.readouterr().out == "2.7.0\n"

    assert run(repository, "version", "check", "--expect", "2.6.2") == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert "expected 2.6.2, the latest release in CHANGELOG.md is 2.7.0" in output.err
    assert "0.0.0" not in output.err


def test_before_the_first_release_there_is_no_version_to_report(
    repository: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_lf(
        repository / "CHANGELOG.md",
        "# Changelog\n\n## [Unreleased]\n\n- All functionality and files.\n",
    )
    assert run(repository, "version", "check") == 1
    assert "records no release yet" in capsys.readouterr().err


def test_version_bump_names_the_changelog_release_as_the_step(
    repository: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(repository, "version", "bump", "2.8.0") == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert "no version sites" in output.err
    assert "release changelog release X.Y.Z" in output.err
    assert git(repository, "status", "--porcelain") == ""


def test_build_refuses_because_the_tag_is_the_release(
    repository: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "dist"
    assert run(repository, "build", "--out", str(out)) == 1
    assert "nothing to build" in capsys.readouterr().err
    assert not out.exists()


def test_tag_create_reads_the_version_from_the_changelog(
    repository: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(repository, "tag", "create", "2.8.0", "--offline") == 1
    assert "latest released section must be [2.8.0]" in capsys.readouterr().err
    assert git(repository, "tag", "--list") == ""

    assert run(repository, "tag", "create", "2.7.0", "--offline") == 0
    assert capsys.readouterr().out == "v2.7.0\n"
    assert git(repository, "cat-file", "-t", "v2.7.0").strip() == "tag"


def test_verify_checks_the_remote_tag_and_the_forge(
    repository: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    latest = "v2.7.0"
    monkeypatch.setattr(verify, "latest_tag", lambda forge: latest)
    git(repository, "tag", "-a", "v2.7.0", "-m", "version 2.7.0")

    assert run(repository, "verify", "--version", "2.7.0") == 1
    assert "v2.7.0 is not on origin" in capsys.readouterr().err

    git(repository, "push", "-q", "origin", "refs/tags/v2.7.0")
    assert run(repository, "verify", "--version", "2.7.0") == 0
    output = capsys.readouterr()
    assert output.out == ""
    assert "» Verified origin has v2.7.0 at " in output.err
    assert "» Verified github reports v2.7.0 as the latest release" in output.err

    # Without --version, the changelog says which release to verify.
    assert run(repository, "verify") == 0
    assert "Verified origin has v2.7.0" in capsys.readouterr().err

    latest = "v2.6.2"
    assert run(repository, "verify", "--version", "2.7.0") == 1
    assert "reports v2.6.2 as latest, not v2.7.0" in capsys.readouterr().err

    (repository / "artifacts.json").write_text('{"artifacts": []}', encoding="utf-8")
    assert run(repository, "verify", str(repository / "artifacts.json")) == 1
    assert "takes no manifest" in capsys.readouterr().err


def test_status_has_nothing_to_publish(
    repository: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(forge_api, "release_exists", lambda forge, tag: False)
    git(repository, "tag", "-a", "v2.7.0", "-m", "version 2.7.0")
    git(repository, "push", "-q", "origin", "refs/tags/v2.7.0")

    assert run(repository, "status", "2.7.0") == 1
    output = capsys.readouterr().out
    assert "ok       changelog" in output
    assert "ok       tag " in output
    assert "ok       tag pushed" in output
    assert "ok       index          this ecosystem publishes nothing" in output
    assert "pending  forge release" in output


def test_a_declared_version_file_still_counts(
    repository: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The ecosystem defaults to no sites; a project may still declare one, and
    # then it is checked like any other.
    write_lf(repository / "theme.toml", 'version = "2.6.2"\n')
    write_lf(
        repository / ".releasing.toml",
        'repository = "foundata/skeletons"\necosystem = "source-repository"\n'
        'version-files = ["theme.toml"]\n',
    )
    assert run(repository, "version", "check") == 1
    assert "latest released section must be [2.6.2]" in capsys.readouterr().err
