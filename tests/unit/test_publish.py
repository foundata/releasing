# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later

import json
from pathlib import Path

import pytest

from releasing import processes, publish
from releasing.artifacts import build_manifest, dump_manifest, load_manifest


def released(tmp_path: Path, *, extra_file: bool = False) -> Path:
    directory = tmp_path / "dist"
    directory.mkdir()
    (directory / "example-1.0.0.tar.gz").write_bytes(b"source distribution")
    (directory / "example-1.0.0-py3-none-any.whl").write_bytes(b"wheel")
    manifest = build_manifest(
        sorted(directory.iterdir()),
        repository="foundata/example",
        version="1.0.0",
        source_revision="a" * 40,
    )
    (directory / "artifacts.json").write_text(dump_manifest(manifest), encoding="utf-8")
    if extra_file:
        (directory / "example-0.9.0.tar.gz").write_bytes(b"left over from last time")
    return directory


def test_plan_lists_exactly_the_manifest_files(tmp_path: Path) -> None:
    directory = released(tmp_path)
    manifest = load_manifest(directory / "artifacts.json")
    prepared = publish.plan(manifest, directory, index="pypi")
    assert [path.name for path in prepared.files] == [
        "example-1.0.0-py3-none-any.whl",
        "example-1.0.0.tar.gz",
    ]
    assert (prepared.index, prepared.version) == ("pypi", "1.0.0")


def test_a_stale_artifact_beside_the_manifest_is_refused(tmp_path: Path) -> None:
    # The case a shell glob cannot see: dist/ holds last release's file too.
    directory = released(tmp_path, extra_file=True)
    manifest = load_manifest(directory / "artifacts.json")
    with pytest.raises(publish.PublishError, match="not in the manifest"):
        publish.plan(manifest, directory, index="pypi")


def test_an_altered_file_is_refused(tmp_path: Path) -> None:
    directory = released(tmp_path)
    manifest = load_manifest(directory / "artifacts.json")
    (directory / "example-1.0.0.tar.gz").write_bytes(b"tampered")
    with pytest.raises(publish.PublishError, match="SHA-256 differs"):
        publish.plan(manifest, directory, index="pypi")


def test_a_missing_file_is_refused(tmp_path: Path) -> None:
    directory = released(tmp_path)
    manifest = load_manifest(directory / "artifacts.json")
    (directory / "example-1.0.0.tar.gz").unlink()
    with pytest.raises(publish.PublishError, match="missing"):
        publish.plan(manifest, directory, index="pypi")


def test_an_index_that_publishes_nothing_is_refused(tmp_path: Path) -> None:
    directory = released(tmp_path)
    manifest = load_manifest(directory / "artifacts.json")
    with pytest.raises(publish.PublishError, match="publishes nothing"):
        publish.plan(manifest, directory, index="none")


def test_upload_sends_the_planned_paths_and_no_credential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = released(tmp_path)
    manifest = load_manifest(directory / "artifacts.json")
    prepared = publish.plan(manifest, directory, index="pypi")
    seen: list[list[str]] = []
    monkeypatch.setattr(processes, "executable", lambda name: Path("/usr/bin") / name)

    def record(argv: list[str], **kwargs: object) -> str:
        seen.append(argv)
        return ""

    monkeypatch.setattr(processes, "run", record)

    assert publish.execute(prepared) == [
        "example-1.0.0-py3-none-any.whl",
        "example-1.0.0.tar.gz",
    ]
    argv = seen[0]
    assert argv[1] == "publish"
    assert [Path(item).name for item in argv[2:]] == [
        "example-1.0.0-py3-none-any.whl",
        "example-1.0.0.tar.gz",
    ]
    # A credential is never an argument; the index tool reads its own.
    assert not any("token" in item.lower() for item in argv)


def test_a_collection_is_published_one_file_at_a_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = tmp_path / "dist"
    directory.mkdir()
    (directory / "foundata-linux-1.4.0.tar.gz").write_bytes(b"collection")
    manifest = build_manifest(
        [directory / "foundata-linux-1.4.0.tar.gz"],
        repository="foundata/ansible-collection-linux",
        version="1.4.0",
        source_revision=None,
    )
    (directory / "artifacts.json").write_text(dump_manifest(manifest), encoding="utf-8")
    prepared = publish.plan(
        load_manifest(directory / "artifacts.json"), directory, index="galaxy"
    )
    seen: list[list[str]] = []
    monkeypatch.setattr(processes, "executable", lambda name: Path("/usr/bin") / name)

    def record(argv: list[str], **kwargs: object) -> str:
        seen.append(argv)
        return ""

    monkeypatch.setattr(processes, "run", record)
    publish.execute(prepared)
    assert seen[0][1:3] == ["collection", "publish"]


def test_dry_run_sends_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    directory = released(tmp_path)
    prepared = publish.plan(
        load_manifest(directory / "artifacts.json"), directory, index="pypi"
    )

    def refuse(*args: object, **kwargs: object) -> object:
        raise AssertionError("nothing may be uploaded during a dry run")

    monkeypatch.setattr(processes, "run", refuse)
    assert publish.execute(prepared, dry_run=True) == [
        "example-1.0.0-py3-none-any.whl",
        "example-1.0.0.tar.gz",
    ]


def test_a_manifest_from_another_gate_is_accepted(tmp_path: Path) -> None:
    # Only the artifacts list is required, so a gate writing its own extra
    # keys can still be published from.
    directory = tmp_path / "dist"
    directory.mkdir()
    (directory / "example-1.0.0.tar.gz").write_bytes(b"source distribution")
    manifest = build_manifest(
        [directory / "example-1.0.0.tar.gz"],
        repository="foundata/example",
        version="1.0.0",
        source_revision="a" * 40,
    )
    (directory / "artifacts.json").write_text(
        dump_manifest(manifest, extra={"guideRevision": "b" * 40}), encoding="utf-8"
    )
    loaded = load_manifest(directory / "artifacts.json")
    assert json.loads((directory / "artifacts.json").read_text())["guideRevision"]
    assert publish.plan(loaded, directory, index="pypi").files == (
        directory / "example-1.0.0.tar.gz",
    )


def test_a_galaxy_token_is_only_read_for_a_named_server() -> None:
    # ansible-core builds the variable name from the server's own name and
    # only for a server GALAXY_SERVER_LIST names. A token set under any other
    # name reaches nobody, which is an unauthenticated upload rather than a
    # working one, so the warning has to fire for it.
    stray = {
        "ANSIBLE_GALAXY_SERVER_TOKEN": "secret",
        "ANSIBLE_GALAXY_TOKEN_PATH": "/nonexistent",
    }
    assert publish.credential_warning("galaxy", stray) is not None
    unlisted = {
        "ANSIBLE_GALAXY_SERVER_GALAXY_TOKEN": "secret",
        "ANSIBLE_GALAXY_TOKEN_PATH": "/nonexistent",
    }
    assert publish.credential_warning("galaxy", unlisted) is not None
    named = {**unlisted, "ANSIBLE_GALAXY_SERVER_LIST": "galaxy"}
    assert publish.credential_warning("galaxy", named) is None


def test_a_galaxy_credential_can_come_from_a_token_file(tmp_path: Path) -> None:
    token = tmp_path / "galaxy_token"
    token.write_text("", encoding="utf-8")
    environ = {"ANSIBLE_GALAXY_TOKEN_PATH": str(token)}
    # ansible-core creates the file empty on first use; empty is no credential.
    assert publish.credential_warning("galaxy", environ) is not None
    token.write_text("token: secret\n", encoding="utf-8")
    assert publish.credential_warning("galaxy", environ) is None


def test_a_pypi_credential_is_a_token_or_a_password() -> None:
    assert publish.credential_warning("pypi", {}) is not None
    assert publish.credential_warning("pypi", {"UV_PUBLISH_TOKEN": "secret"}) is None
    assert publish.credential_warning("pypi", {"UV_PUBLISH_PASSWORD": "secret"}) is None
