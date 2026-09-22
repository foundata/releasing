# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later

import io
import pickle
import tarfile
import tempfile
from pathlib import Path

import pytest

from releasing import _source_export, processes
from releasing.build import BuildError, export


def test_build_reexports_the_shared_export_interface() -> None:
    assert export is _source_export.export
    assert BuildError is _source_export.BuildError


def test_build_error_preserves_its_public_exception_identity() -> None:
    assert BuildError.__module__ == "releasing.build"
    assert BuildError.__qualname__ == "BuildError"
    assert BuildError.__bases__ == (RuntimeError,)
    serialized = b"creleasing.build\nBuildError\np0\n(Vexport failed\np1\ntp2\nRp3\n."
    assert pickle.dumps(BuildError("export failed"), protocol=0) == serialized
    restored = pickle.loads(serialized)
    assert type(restored) is BuildError
    assert str(restored) == "export failed"


@pytest.fixture
def scratch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "temporary"
    directory.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(directory))
    return directory


def archive_git(
    monkeypatch: pytest.MonkeyPatch, members: list[tarfile.TarInfo]
) -> list[Path]:
    archives: list[Path] = []

    def git(
        root: Path, *arguments: str, stdout: Path | None = None, **_: object
    ) -> str:
        assert arguments == ("archive", "--format=tar", "revision")
        assert stdout is not None
        archives.append(stdout)
        with tarfile.open(stdout, "w:") as stream:
            for member in members:
                content = b"contents\n" if member.isfile() else b""
                member.size = len(content)
                stream.addfile(member, io.BytesIO(content))
        return ""

    monkeypatch.setattr(processes, "git", git)
    return archives


def test_export_preserves_files_links_and_the_caller_directory(
    tmp_path: Path, scratch: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = tarfile.TarInfo("directory")
    directory.type = tarfile.DIRTYPE
    directory.mode = 0o755
    executable = tarfile.TarInfo("directory/run")
    executable.mode = 0o755
    symbolic = tarfile.TarInfo("symbolic")
    symbolic.type = tarfile.SYMTYPE
    symbolic.linkname = "directory/run"
    hard = tarfile.TarInfo("hard")
    hard.type = tarfile.LNKTYPE
    hard.linkname = "directory/run"
    hard.mode = 0o755
    archives = archive_git(monkeypatch, [directory, executable, symbolic, hard])
    destination = tmp_path / "destination"
    destination.mkdir()
    (destination / "unrelated").write_bytes(b"caller-owned")

    export(tmp_path, "revision", destination)

    assert (destination / "unrelated").read_bytes() == b"caller-owned"
    assert (destination / "directory/run").read_bytes() == b"contents\n"
    assert (destination / "directory/run").stat().st_mode & 0o777 == 0o755
    assert (destination / "symbolic").readlink() == Path("directory/run")
    assert (destination / "hard").samefile(destination / "directory/run")
    assert len(archives) == 1
    assert archives[0].name == "source.tar"
    assert archives[0].parent.parent == scratch
    assert not archives[0].parent.exists()
    assert list(scratch.iterdir()) == []


def test_export_preserves_a_git_failure_and_cleans_its_partial_archive(
    tmp_path: Path, scratch: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    failure = processes.ProcessError("git failed with status 128:\narchive failed")
    archives: list[Path] = []

    def git(
        root: Path, *arguments: str, stdout: Path | None = None, **_: object
    ) -> str:
        assert stdout is not None
        archives.append(stdout)
        stdout.write_bytes(b"partial archive")
        raise failure

    monkeypatch.setattr(processes, "git", git)
    destination = tmp_path / "destination"
    with pytest.raises(processes.ProcessError) as caught:
        export(tmp_path, "revision", destination)
    assert caught.value is failure
    assert destination.is_dir()
    assert list(destination.iterdir()) == []
    assert len(archives) == 1
    assert not archives[0].parent.exists()
    assert list(scratch.iterdir()) == []


def test_export_wraps_an_unreadable_archive_and_removes_it(
    tmp_path: Path, scratch: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def git(
        root: Path, *arguments: str, stdout: Path | None = None, **_: object
    ) -> str:
        assert stdout is not None
        stdout.write_bytes(b"not a tar archive")
        return ""

    monkeypatch.setattr(processes, "git", git)
    destination = tmp_path / "destination"
    with pytest.raises(BuildError) as caught:
        export(tmp_path, "revision", destination)
    assert type(caught.value) is BuildError
    assert isinstance(caught.value.__cause__, tarfile.ReadError)
    assert str(caught.value) == (
        f"cannot extract the exported revision: {caught.value.__cause__}"
    )
    assert list(destination.iterdir()) == []
    assert list(scratch.iterdir()) == []


@pytest.mark.parametrize(
    "name", ["../escape", "/absolute", "nested/../../escape", r"a\b"]
)
@pytest.mark.parametrize("kind", [tarfile.REGTYPE, tarfile.SYMTYPE])
def test_export_rejects_unsafe_names_before_extracting_any_member(
    tmp_path: Path,
    scratch: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    kind: bytes,
) -> None:
    unsafe = tarfile.TarInfo(name)
    unsafe.type = kind
    unsafe.linkname = "valid"
    archive_git(monkeypatch, [tarfile.TarInfo("valid"), unsafe])
    destination = tmp_path / "destination"
    with pytest.raises(BuildError) as caught:
        export(tmp_path, "revision", destination)
    assert type(caught.value) is BuildError
    assert str(caught.value) == f"unsafe archive member {name!r}"
    assert caught.value.__cause__ is None
    assert list(destination.iterdir()) == []
    assert list(scratch.iterdir()) == []


@pytest.mark.parametrize("kind", [tarfile.FIFOTYPE, tarfile.CHRTYPE, tarfile.BLKTYPE])
def test_export_rejects_special_members_before_extracting_any_member(
    tmp_path: Path, scratch: Path, monkeypatch: pytest.MonkeyPatch, kind: bytes
) -> None:
    special = tarfile.TarInfo("special")
    special.type = kind
    archive_git(monkeypatch, [tarfile.TarInfo("valid"), special])
    destination = tmp_path / "destination"
    with pytest.raises(BuildError) as caught:
        export(tmp_path, "revision", destination)
    assert str(caught.value) == "unsupported archive member special"
    assert caught.value.__cause__ is None
    assert list(destination.iterdir()) == []
    assert list(scratch.iterdir()) == []


@pytest.mark.parametrize("write_through", [False, True])
def test_export_keeps_outward_symlinks_but_rejects_writes_through_them(
    tmp_path: Path, scratch: Path, monkeypatch: pytest.MonkeyPatch, write_through: bool
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "file").write_bytes(b"unchanged")
    symbolic = tarfile.TarInfo("link")
    symbolic.type = tarfile.SYMTYPE
    symbolic.linkname = "../outside"
    members = [symbolic]
    if write_through:
        members.append(tarfile.TarInfo("link/file"))
    archive_git(monkeypatch, members)
    destination = tmp_path / "destination"
    if write_through:
        with pytest.raises(BuildError) as caught:
            export(tmp_path, "revision", destination)
        assert isinstance(caught.value.__cause__, tarfile.OutsideDestinationError)
        assert str(caught.value) == (
            f"cannot extract the exported revision: {caught.value.__cause__}"
        )
    else:
        export(tmp_path, "revision", destination)
    assert (destination / "link").readlink() == Path("../outside")
    assert (outside / "file").read_bytes() == b"unchanged"
    assert list(scratch.iterdir()) == []


def test_export_does_not_roll_back_a_partially_extracted_destination(
    tmp_path: Path, scratch: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive_git(monkeypatch, [tarfile.TarInfo("first"), tarfile.TarInfo("blocked")])
    destination = tmp_path / "destination"
    (destination / "blocked").mkdir(parents=True)
    (destination / "unrelated").write_bytes(b"caller-owned")
    with pytest.raises(BuildError) as caught:
        export(tmp_path, "revision", destination)
    assert isinstance(caught.value.__cause__, IsADirectoryError)
    assert str(caught.value) == (
        f"cannot extract the exported revision: {caught.value.__cause__}"
    )
    assert (destination / "first").read_bytes() == b"contents\n"
    assert (destination / "blocked").is_dir()
    assert (destination / "unrelated").read_bytes() == b"caller-owned"
    assert list(scratch.iterdir()) == []


def test_destination_creation_errors_are_not_wrapped(
    tmp_path: Path, scratch: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archives = archive_git(monkeypatch, [])
    destination = tmp_path / "destination"
    destination.write_bytes(b"caller-owned")
    with pytest.raises(FileExistsError):
        export(tmp_path, "revision", destination)
    assert destination.read_bytes() == b"caller-owned"
    assert archives == []
    assert list(scratch.iterdir()) == []


def test_temporary_directory_creation_errors_are_not_wrapped(
    tmp_path: Path, scratch: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    failure = PermissionError("cannot create temporary directory")

    def fail(*, prefix: str) -> None:
        assert prefix == "releasing-export-"
        raise failure

    archives = archive_git(monkeypatch, [])
    monkeypatch.setattr(tempfile, "TemporaryDirectory", fail)
    destination = tmp_path / "destination"
    with pytest.raises(PermissionError) as caught:
        export(tmp_path, "revision", destination)
    assert caught.value is failure
    assert destination.is_dir()
    assert archives == []
    assert list(scratch.iterdir()) == []


@pytest.mark.parametrize("invalid_archive", [False, True])
def test_cleanup_failure_takes_precedence_over_an_export_error(
    tmp_path: Path,
    scratch: Path,
    monkeypatch: pytest.MonkeyPatch,
    invalid_archive: bool,
) -> None:
    failure = PermissionError("cannot clean temporary directory")
    cleanup = tempfile.TemporaryDirectory.cleanup

    def fail(directory: tempfile.TemporaryDirectory[str]) -> None:
        # Release the test files before simulating the cleanup failure.
        cleanup(directory)
        raise failure

    name = "../escape" if invalid_archive else "valid"
    archive_git(monkeypatch, [tarfile.TarInfo(name)])
    monkeypatch.setattr(tempfile.TemporaryDirectory, "cleanup", fail)
    destination = tmp_path / "destination"
    with pytest.raises(PermissionError) as caught:
        export(tmp_path, "revision", destination)
    assert caught.value is failure
    if invalid_archive:
        assert type(caught.value.__context__) is BuildError
        assert str(caught.value.__context__) == "unsafe archive member '../escape'"
        assert list(destination.iterdir()) == []
    else:
        assert caught.value.__context__ is None
        assert (destination / "valid").read_bytes() == b"contents\n"
    assert list(scratch.iterdir()) == []
