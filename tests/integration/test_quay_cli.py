# SPDX-FileCopyrightText: foundata GmbH <https://foundata.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""The README of a tagged revision becomes the description of Quay repositories."""

import json
import os
import subprocess
import urllib.request
from pathlib import Path

import pytest

from releasing import cli
from tests.support import FakeQuay, write_lf

pytestmark = pytest.mark.integration
GIT_ENV = {
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
}
README = """# Example image

<!--
SPDX-License-Identifier: GPL-3.0-or-later
-->

- [Usage](#usage)

## Usage<a id="usage"></a>

See [`DEVELOPMENT.md`](DEVELOPMENT.md).
"""
EXPECTED = """# Example image

- [Usage](https://github.com/foundata/oci-example/blob/refs/tags/v1.0.0/README.md#usage)

## Usage

See [`DEVELOPMENT.md`](https://github.com/foundata/oci-example/blob/refs/tags/v1.0.0/DEVELOPMENT.md).
"""
BASE = ["-o", "foundata", "-r", "oci-example", "--ref", "refs/tags/v1.0.0"]


def git(cwd: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", "-C", str(cwd), *arguments],
        env={**os.environ, **GIT_ENV},
        capture_output=True,
        timeout=60,
        check=True,
    )


@pytest.fixture
def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for name, value in GIT_ENV.items():
        monkeypatch.setenv(name, value)
    root = tmp_path / "oci-example"
    root.mkdir()
    write_lf(root / "README.md", README)
    write_lf(root / "DEVELOPMENT.md", "# Development\n")
    git(tmp_path, "init", "-q", "-b", "main", str(root))
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "repository: describe the image")
    git(root, "tag", "-a", "v1.0.0", "-m", "version 1.0.0")
    # The working tree moves on; the description must come from the tag.
    write_lf(root / "README.md", "# Unreleased\n")
    return root


@pytest.fixture
def token_file(tmp_path: Path) -> Path:
    path = tmp_path / "quay.token"
    path.write_bytes(b"secret-token\n")
    path.chmod(0o600)
    return path


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeQuay:
    server = FakeQuay()
    monkeypatch.setattr(urllib.request, "urlopen", server)
    return server


def run(repository: Path, *arguments: str) -> int:
    return cli.main(
        ["quay", "description-set", "--project", str(repository), *arguments]
    )


def test_the_tagged_readme_is_published_and_each_page_printed(
    repository: Path,
    token_file: Path,
    fake: FakeQuay,
    capsys: pytest.CaptureFixture[str],
) -> None:
    status = run(
        repository,
        *BASE,
        "--token-file",
        str(token_file),
        "quay.io/foundata/example",
        "quay.io/foundata/example-generator",
    )
    output = capsys.readouterr()
    assert status == 0, output.err
    assert fake.methods() == ["GET", "PUT", "GET", "GET", "PUT", "GET"]
    assert json.loads(fake.requests[1].data) == {"description": EXPECTED}
    assert fake.requests[4].full_url == (
        "https://quay.io/api/v1/repository/foundata/example-generator"
    )
    assert output.out == (
        "https://quay.io/repository/foundata/example\n"
        "https://quay.io/repository/foundata/example-generator\n"
    )
    assert "Published the description of quay.io/foundata/example" in output.err
    assert "secret-token" not in output.out + output.err


def test_a_dry_run_needs_no_token_and_writes_nothing(
    repository: Path, fake: FakeQuay, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(repository, *BASE, "--dry-run", "quay.io/foundata/example") == 0
    output = capsys.readouterr()
    assert fake.methods() == ["GET"]
    assert output.out == ""
    assert "+## Usage" in output.err


def test_a_write_needs_a_token_file(
    repository: Path, fake: FakeQuay, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as stopped:
        run(repository, *BASE, "quay.io/foundata/example")
    assert stopped.value.code == 2
    assert "--token-file is required" in capsys.readouterr().err
    assert fake.requests == []


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (["--ref", "refs/tags/v1.0.0"], "name the forge repository"),
        ([*BASE, "--source-path", "missing.md"], "cannot read missing.md"),
        (["-o", "foundata", "-r", "x", "--ref", "refs/tags/v9.9.9"], "cannot resolve"),
        (["-o", "foundata", "-r", "x", "--ref", "v1.0.0"], "--ref requires"),
        ([*BASE, "--api-url", "http://quay.io/api/v1"], "HTTPS"),
    ],
)
def test_nothing_is_requested_when_the_input_is_wrong(
    repository: Path,
    token_file: Path,
    fake: FakeQuay,
    capsys: pytest.CaptureFixture[str],
    arguments: list[str],
    message: str,
) -> None:
    status = run(
        repository,
        *arguments,
        "--token-file",
        str(token_file),
        "quay.io/foundata/example",
    )
    assert status == 1
    assert message in capsys.readouterr().err
    assert fake.requests == []


def test_a_relative_link_missing_at_the_tag_is_refused(
    repository: Path,
    token_file: Path,
    fake: FakeQuay,
    capsys: pytest.CaptureFixture[str],
) -> None:
    git(repository, "rm", "-q", "DEVELOPMENT.md")
    git(repository, "commit", "-q", "-m", "repository: drop the development guide")
    git(repository, "tag", "-a", "v1.0.1", "-m", "version 1.0.1")
    status = run(
        repository,
        "-o",
        "foundata",
        "-r",
        "oci-example",
        "--ref",
        "refs/tags/v1.0.1",
        "--token-file",
        str(token_file),
        "quay.io/foundata/example",
    )
    assert status == 1
    assert "'DEVELOPMENT.md': local target does not exist" in capsys.readouterr().err
    assert fake.requests == []


def test_a_directory_is_not_a_document(
    repository: Path,
    token_file: Path,
    fake: FakeQuay,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (repository / "docs").mkdir()
    write_lf(repository / "docs" / "README.md", "# Docs\n")
    git(repository, "add", "docs")
    git(repository, "commit", "-q", "-m", "repository: add the documentation")
    status = run(
        repository,
        "-o",
        "foundata",
        "-r",
        "oci-example",
        "--ref",
        "refs/heads/main",
        "--source-path",
        "docs",
        "--token-file",
        str(token_file),
        "quay.io/foundata/example",
    )
    assert status == 1
    assert "docs is not a file in refs/heads/main" in capsys.readouterr().err
    assert fake.requests == []
