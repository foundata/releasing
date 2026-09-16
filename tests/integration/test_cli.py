# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import stat
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from tests.support import ROOT, SCRIPT, TRANSFORMER

pytestmark = pytest.mark.integration
BASE = ["-o", "foundata", "-r", "example"]


def invoke(cwd: Path, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-I", str(SCRIPT), *arguments],
        cwd=cwd,
        env={**os.environ, "PATH": str(cwd / "no-programs")},
        capture_output=True,
        timeout=15,
        check=False,
    )


def source(tmp_path: Path, content: bytes = b"[guide](./docs.md#start)\n") -> Path:
    path = tmp_path / "README.md"
    path.write_bytes(content)
    path.chmod(0o640)
    return path


def snapshot(path: Path) -> tuple[bytes, int, int, int, int]:
    content = path.read_bytes()
    metadata = path.stat()
    # Reads may change atime; none of these properties should change on a read.
    return (
        content,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


@pytest.mark.parametrize("mode", [["--stdout"], ["--output", "-"]])
def test_stdout_is_only_markdown_and_never_changes_input(
    tmp_path: Path, mode: list[str]
) -> None:
    path = source(tmp_path)
    before = snapshot(path)
    result = invoke(tmp_path, *BASE, "--strict", *mode, str(path))
    assert result.returncode == 0, result.stderr
    assert (
        result.stdout
        == b"[guide](https://github.com/foundata/example/blob/main/docs.md#start)\n"
    )
    assert result.stderr == b""
    assert snapshot(path) == before


def test_separate_file_output_preserves_existing_destination_permissions(
    tmp_path: Path,
) -> None:
    path = source(tmp_path)
    output = tmp_path / "prepared.md"
    output.write_bytes(b"old output")
    output.chmod(0o604)
    result = invoke(tmp_path, *BASE, "--output", str(output), str(path))
    assert result.returncode == 0, result.stderr
    assert result.stdout == b""
    assert b"https://github.com/foundata/example/" in output.read_bytes()
    assert path.read_bytes() == b"[guide](./docs.md#start)\n"
    assert stat.S_IMODE(output.stat().st_mode) == 0o604
    assert not list(tmp_path.glob(".prepared.md.*"))


def test_in_place_preserves_permissions_and_is_noop_on_second_run(
    tmp_path: Path,
) -> None:
    path = source(tmp_path)
    first = invoke(tmp_path, *BASE, str(path))
    assert first.returncode == 0, first.stderr
    assert first.stdout == b""
    assert b"--- " in first.stderr
    assert stat.S_IMODE(path.stat().st_mode) == 0o640
    before = snapshot(path)
    second = invoke(tmp_path, *BASE, str(path))
    assert second.returncode == 0
    assert b"Unchanged:" in second.stderr
    assert snapshot(path) == before


@pytest.mark.parametrize(
    "ref, url_ref, raw_ref",
    [
        (["-b", "feature/docs"], "feature/docs", "refs/heads/feature/docs"),
        (["--ref", "refs/heads/main"], "refs/heads/main", "refs/heads/main"),
        (["--ref", "refs/tags/v1.0.0"], "refs/tags/v1.0.0", "refs/tags/v1.0.0"),
        (["--ref", "a" * 40], "a" * 40, "a" * 40),
    ],
)
def test_explicit_refs_apply_to_both_url_bases(
    tmp_path: Path, ref: list[str], url_ref: str, raw_ref: str
) -> None:
    path = source(tmp_path, b"[guide](docs.md) ![logo](logo.avif)\n")
    result = invoke(tmp_path, *BASE, *ref, "--stdout", str(path))
    assert result.returncode == 0, result.stderr
    assert (
        f"[guide](https://github.com/foundata/example/blob/{url_ref}/docs.md)".encode()
        in result.stdout
    )
    assert (
        f"![logo](https://raw.githubusercontent.com/foundata/example/{raw_ref}/logo.avif)".encode()
        in result.stdout
    )


def test_source_path_is_independent_of_input_and_output_directories(
    tmp_path: Path,
) -> None:
    path = source(tmp_path, b"[guide](../guide.md)\n")
    result = invoke(
        tmp_path,
        *BASE,
        "--strict",
        "--source-path",
        "docs/README.md",
        "--stdout",
        str(path),
    )
    assert result.returncode == 0, result.stderr
    assert (
        result.stdout
        == b"[guide](https://github.com/foundata/example/blob/main/guide.md)\n"
    )


@pytest.mark.parametrize("options", [[], ["--output", "prepared.md"], ["--stdout"]])
def test_strict_failure_writes_nothing(tmp_path: Path, options: list[str]) -> None:
    path = source(tmp_path, b"[good](./guide.md) [bad](/root.md)\n")
    output = tmp_path / "prepared.md"
    output.write_bytes(b"existing")
    before = snapshot(path)
    result = invoke(tmp_path, *BASE, "--strict", *options, str(path))
    assert result.returncode == 1
    assert b"root-relative" in result.stderr
    assert b"README.md:1:" in result.stderr
    assert result.stdout == b""
    assert snapshot(path) == before
    assert output.read_bytes() == b"existing"


def test_all_batch_inputs_are_validated_before_writing(tmp_path: Path) -> None:
    first = source(tmp_path)
    second = tmp_path / "other.md"
    second.write_text("[bad](/root.md)", encoding="utf-8")
    before = snapshot(first)
    result = invoke(tmp_path, *BASE, "--strict", str(first), str(second))
    assert result.returncode == 1
    assert snapshot(first) == before


@pytest.mark.parametrize("alias", ["same", "hardlink", "symlink"])
def test_out_of_place_refuses_aliases_of_input(tmp_path: Path, alias: str) -> None:
    path = source(tmp_path)
    output = tmp_path / "alias.md"
    if alias == "same":
        output = path
    elif alias == "hardlink":
        output.hardlink_to(path)
    else:
        output.symlink_to(path)
    result = invoke(tmp_path, *BASE, "--output", str(output), str(path))
    assert result.returncode == 1
    assert b"separate regular file" in result.stderr
    assert path.read_bytes() == b"[guide](./docs.md#start)\n"


def test_in_place_refuses_symlink(tmp_path: Path) -> None:
    path = source(tmp_path)
    alias = tmp_path / "alias.md"
    alias.symlink_to(path)
    result = invoke(tmp_path, *BASE, str(alias))
    assert result.returncode == 1
    assert alias.is_symlink()
    assert path.read_bytes() == b"[guide](./docs.md#start)\n"


@pytest.mark.parametrize(
    "data", [b"\xffinvalid", b"\xef\xbb\xbf[x](a)", b"text\0[x](a)"]
)
def test_encoding_failure_does_not_replace_input(tmp_path: Path, data: bytes) -> None:
    path = source(tmp_path, data)
    result = invoke(tmp_path, *BASE, str(path))
    assert result.returncode == 1
    assert path.read_bytes() == data
    assert b"Traceback" not in result.stderr


def test_explicit_bases_work_without_repository_metadata(tmp_path: Path) -> None:
    path = source(tmp_path)
    result = invoke(
        tmp_path,
        "-a",
        "https://raw.example/r/",
        "-u",
        "https://ui.example/r/",
        "--stdout",
        str(path),
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == b"[guide](https://ui.example/r/docs.md#start)\n"


def test_custom_bases_do_not_depend_on_current_directory_names(tmp_path: Path) -> None:
    path = source(tmp_path)
    result = invoke(
        Path("/"),
        "-a",
        "https://raw.example/r/",
        "-u",
        "https://ui.example/r/",
        "--stdout",
        str(path),
    )
    assert result.returncode == 0, result.stderr


def test_failed_atomic_replace_cleans_temporary_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = source(tmp_path)
    output = tmp_path / "prepared.md"
    output.write_bytes(b"existing output")

    def fail_replace(source_path: object, target_path: object) -> None:
        raise OSError("injected replacement failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    assert TRANSFORMER.main([*BASE, "--output", str(output), str(path)]) == 1
    assert output.read_bytes() == b"existing output"
    assert path.read_bytes() == b"[guide](./docs.md#start)\n"
    assert sorted(item.name for item in tmp_path.iterdir()) == [
        "README.md",
        "prepared.md",
    ]


def test_fifo_input_is_rejected_without_reading(tmp_path: Path) -> None:
    path = tmp_path / "input.md"
    os.mkfifo(path)
    result = invoke(tmp_path, *BASE, "--stdout", str(path))
    assert result.returncode == 1
    assert b"regular file" in result.stderr


def test_out_of_place_refuses_implicit_cwd_defaults(tmp_path: Path) -> None:
    result = invoke(tmp_path, "--stdout", str(source(tmp_path)))
    assert result.returncode == 1
    assert b"requires -o and -r" in result.stderr


def test_legacy_cwd_defaults_remain_available_in_place(tmp_path: Path) -> None:
    result = invoke(tmp_path, str(source(tmp_path)))
    assert result.returncode == 0, result.stderr
    assert (
        f"https://github.com/{tmp_path.parent.name}/{tmp_path.name}/blob/main/".encode()
        in (tmp_path / "README.md").read_bytes()
    )


@pytest.mark.parametrize(
    "arguments",
    [
        ["--ref", "main"],
        ["--ref", "refs/tags/../oops"],
        ["-b", "bad branch"],
        ["-b", "main", "--ref", "refs/tags/v1"],
        ["--stdout", "--in-place"],
    ],
)
def test_invalid_ref_or_conflicting_options_fail(
    tmp_path: Path, arguments: list[str]
) -> None:
    path = source(tmp_path)
    result = invoke(tmp_path, *BASE, *arguments, str(path))
    assert result.returncode != 0
    assert b"Traceback" not in result.stderr
    assert path.read_bytes() == b"[guide](./docs.md#start)\n"


def test_missing_input_and_output_parent_fail_cleanly(tmp_path: Path) -> None:
    missing = invoke(tmp_path, *BASE, "absent.md")
    assert missing.returncode == 1
    path = source(tmp_path)
    result = invoke(tmp_path, *BASE, "--output", "absent/prepared.md", str(path))
    assert result.returncode == 1
    assert b"Traceback" not in result.stderr
    assert path.read_bytes() == b"[guide](./docs.md#start)\n"


def test_script_and_project_declare_the_same_runtime_dependency() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    metadata = (
        SCRIPT.read_text(encoding="utf-8")
        .split("# /// script\n", 1)[1]
        .split("# ///", 1)[0]
    )
    script = tomllib.loads(
        "\n".join(line.removeprefix("# ") for line in metadata.splitlines())
    )
    assert script["dependencies"] == project["project"]["dependencies"]
    assert script["requires-python"] == project["project"]["requires-python"]
