# SPDX-FileCopyrightText: foundata GmbH <https://foundata.com>
# SPDX-License-Identifier: GPL-3.0-or-later

import io
import json
import tarfile
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest

from releasing.artifacts import (
    ArtifactError,
    Manifest,
    ManifestEntry,
    build_manifest,
    check,
    dump_manifest,
    inspect,
    load_manifest,
    sha256_file,
    verify_manifest,
)
from tests.support import POSIX_ONLY

HEADERS = (
    "Metadata-Version: 2.4\nName: example\nVersion: 1.2.3\n"
    "Description-Content-Type: text/markdown\n"
)
LINK = "[docs](https://example.test/)"
UNSAFE_MANIFEST_NAMES = (
    "",
    ".",
    "..",
    "../x.whl",
    "./x.whl",
    "/x.whl",
    "nested/x.whl",
    r"nested\x.whl",
    r"C:\release\x.whl",
    "C:x.whl",
    r"\\server\share\x.whl",
    "x.whl:stream",
    "x\x00.whl",
)
PYTHON_VERSION_CASES = (
    ("1.2.3a1", "1.2.3a1"),
    ("1.2.3b2", "1.2.3b2"),
    ("1.2.3rc1", "1.2.3rc1"),
    ("1.2.3.post1", "1.2.3.post1"),
    ("1.2.3.dev2", "1.2.3.dev2"),
    ("1.2.3+linux.1", "1.2.3+linux.1"),
    ("1!1.2.3", "1!1.2.3"),
    ("1.2.3-rc1", "1.2.3rc1"),
    ("1.2.3post1", "1.2.3.post1"),
    ("1.2.3dev2", "1.2.3.dev2"),
    ("1.2.3+Linux_01", "1.2.3+linux.1"),
)


def metadata(version: str, body: str | None) -> str:
    text = HEADERS.replace("1.2.3", version)
    return text + ("\n" if body is None else f"\n# Example\n\n{body}\n")


def wheel(
    directory: Path,
    *,
    version: str = "1.2.3",
    body: str | None = LINK,
    extra: tuple[str, ...] = (),
) -> Path:
    path = directory / f"example-{version}-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("example/__init__.py", "")
        for name in extra:
            archive.writestr(name, "")
        archive.writestr(
            f"example-{version}.dist-info/METADATA", metadata(version, body)
        )
    return path


def _add(archive: tarfile.TarFile, name: str, content: str) -> None:
    data = content.encode()
    info = tarfile.TarInfo(name)
    info.size = len(data)
    archive.addfile(info, io.BytesIO(data))


def sdist(
    directory: Path,
    *,
    version: str = "1.2.3",
    body: str | None = LINK,
    extra: tuple[str, ...] = (),
    symlink: bool = False,
) -> Path:
    path = directory / f"example-{version}.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        _add(archive, f"example-{version}/PKG-INFO", metadata(version, body))
        _add(archive, f"example-{version}/pyproject.toml", "")
        for name in extra:
            _add(archive, f"example-{version}/{name}", "")
        if symlink:
            info = tarfile.TarInfo(f"example-{version}/link")
            info.type = tarfile.SYMTYPE
            info.linkname = "pyproject.toml"
            archive.addfile(info)
    return path


def collection(
    directory: Path,
    *,
    version: str = "1.4.0",
    readme: str = "[guide](https://example.test/guide)",
) -> Path:
    path = directory / f"foundata-linux-{version}.tar.gz"
    info = {
        "collection_info": {
            "namespace": "foundata",
            "name": "linux",
            "version": version,
            "readme": "README.md",
        }
    }
    with tarfile.open(path, "w:gz") as archive:
        _add(archive, "MANIFEST.json", json.dumps(info))
        _add(archive, "README.md", f"# Linux\n\n{readme}\n")
        _add(archive, "roles/x/README.md", "")
    return path


def test_inspect_reads_wheel_sdist_and_collection(tmp_path: Path) -> None:
    built = inspect(wheel(tmp_path))
    assert (built.kind, built.name, built.version) == ("wheel", "example", "1.2.3")
    assert LINK in built.description
    assert "example/__init__.py" in built.members
    source = inspect(sdist(tmp_path))
    assert (source.kind, source.name, source.version) == ("sdist", "example", "1.2.3")
    packed = inspect(collection(tmp_path))
    assert (packed.kind, packed.name, packed.version) == (
        "collection",
        "foundata.linux",
        "1.4.0",
    )
    assert packed.description.startswith("# Linux")


def test_inspect_rejects_unknown_and_unsafe_archives(tmp_path: Path) -> None:
    (tmp_path / "x.zip").write_bytes(b"")
    with pytest.raises(ArtifactError, match="not a wheel"):
        inspect(tmp_path / "x.zip")
    with pytest.raises(ArtifactError, match="unsafe member"):
        inspect(sdist(tmp_path, symlink=True))
    (tmp_path / "broken-1.0.0.tar.gz").write_bytes(b"not a tarball")
    with pytest.raises(ArtifactError, match="cannot read tarball"):
        inspect(tmp_path / "broken-1.0.0.tar.gz")


def test_check_passes_clean_artifacts(tmp_path: Path) -> None:
    built = [inspect(wheel(tmp_path)), inspect(sdist(tmp_path))]
    assert check(built, version="1.2.3", names=["example"]) == []


@pytest.mark.parametrize(
    "filename",
    [
        "example-11.2.3-py3-none-any.whl",
        "example-1.2.30-py3-none-any.whl",
        "example-1.2.3rc1-py3-none-any.whl",
        "example_1.2.3-9.0.0-py3-none-any.whl",
        "example-1.2.3.whl",
    ],
)
def test_check_compares_the_wheel_version_field(tmp_path: Path, filename: str) -> None:
    path = wheel(tmp_path).rename(tmp_path / filename)
    assert check([inspect(path)], version="1.2.3") == [
        f"{filename}: file name does not carry version 1.2.3"
    ]


@pytest.mark.parametrize("kind", ["sdist", "collection"])
@pytest.mark.parametrize("filename_version", ["11.2.3", "1.2.30", "1.2.3rc1"])
def test_check_compares_the_tarball_version_field(
    tmp_path: Path, kind: str, filename_version: str
) -> None:
    path = sdist(tmp_path) if kind == "sdist" else collection(tmp_path, version="1.2.3")
    filename = path.name.replace("1.2.3", filename_version)
    path = path.rename(tmp_path / filename)
    assert check([inspect(path)], version="1.2.3") == [
        f"{filename}: file name does not carry version 1.2.3"
    ]


def test_a_wheel_build_tag_does_not_change_its_version(tmp_path: Path) -> None:
    path = wheel(tmp_path).rename(tmp_path / "example-1.2.3-2build-py3-none-any.whl")
    assert check([inspect(path)], version="1.2.3") == []


@pytest.mark.parametrize("version, filename_version", PYTHON_VERSION_CASES)
def test_wheels_accept_python_versions_and_normalized_filenames(
    tmp_path: Path, version: str, filename_version: str
) -> None:
    path = wheel(tmp_path, version=version).rename(
        tmp_path / f"example-{filename_version}-py3-none-any.whl"
    )
    assert check([inspect(path)], version=version) == []


@pytest.mark.parametrize("version, filename_version", PYTHON_VERSION_CASES)
def test_sdists_accept_python_versions_and_normalized_filenames(
    tmp_path: Path, version: str, filename_version: str
) -> None:
    path = sdist(tmp_path, version=version).rename(
        tmp_path / f"example-{filename_version}.tar.gz"
    )
    assert check([inspect(path)], version=version) == []


def test_collection_prerelease_versions_keep_their_hyphens(tmp_path: Path) -> None:
    path = collection(tmp_path, version="1.2.3-rc1")
    assert check([inspect(path)], version="1.2.3-rc1") == []


def test_check_names_each_defect(tmp_path: Path) -> None:
    built = [
        inspect(wheel(tmp_path, version="1.2.4")),
        inspect(
            sdist(
                tmp_path,
                body="[guide](./docs/guide.md) ![shot](assets/x.png)",
                extra=("src/__pycache__/x.pyc", ".mypy_cache/y", "z.orig"),
            )
        ),
    ]
    problems = check(built, version="1.2.3", names=["example", "example-gui"])
    assert any("metadata version 1.2.4 != 1.2.3" in p for p in problems)
    assert any("file name does not carry version 1.2.3" in p for p in problems)
    assert any(
        "2 relative destination(s)" in p and "'./docs/guide.md'" in p for p in problems
    )
    assert any(
        "generated path example-1.2.3/src/__pycache__/x.pyc" in p for p in problems
    )
    assert any("generated path example-1.2.3/.mypy_cache/y" in p for p in problems)
    assert any("generated file example-1.2.3/z.orig" in p for p in problems)
    assert any("no artifact for example-gui" in p for p in problems)


def test_check_flags_an_empty_description_and_collection_links(tmp_path: Path) -> None:
    assert check([inspect(sdist(tmp_path, body=None))], version="1.2.3") == [
        "example-1.2.3.tar.gz: description is empty; the index page would be blank"
    ]
    packed = inspect(collection(tmp_path, readme="[guide](roles/x/README.md)"))
    problems = check([packed], version="1.4.0")
    assert len(problems) == 1
    assert "relative destination" in problems[0]


def test_manifest_round_trip_and_verification(tmp_path: Path) -> None:
    files = [wheel(tmp_path), sdist(tmp_path)]
    manifest = build_manifest(
        files, repository="foundata/example", version="1.2.3", source_revision="a" * 40
    )
    text = dump_manifest(manifest)
    data = json.loads(text)
    assert data["schemaVersion"] == 1
    assert data["artifacts"][0] == {
        "filename": files[0].name,
        "sha256": sha256_file(files[0]),
        "size": files[0].stat().st_size,
    }
    (tmp_path / "artifacts.json").write_text(text, encoding="utf-8")
    loaded = load_manifest(tmp_path / "artifacts.json")
    assert loaded.artifacts == manifest.artifacts
    assert loaded.source_revision == "a" * 40
    assert verify_manifest(loaded, tmp_path) == []
    files[1].write_bytes(b"tampered")
    wheel(tmp_path, version="9.9.9")
    problems = verify_manifest(loaded, tmp_path)
    assert "example-1.2.3.tar.gz: SHA-256 differs from the manifest" in problems
    assert "example-9.9.9-py3-none-any.whl: not in the manifest" in problems
    files[0].unlink()
    assert "example-1.2.3-py3-none-any.whl: missing" in verify_manifest(
        loaded, tmp_path
    )


def test_manifest_accepts_the_minimal_compatible_shape(tmp_path: Path) -> None:
    path = tmp_path / "artifacts.json"
    path.write_text(
        json.dumps({"artifacts": [{"filename": "x.whl", "sha256": "0" * 64}]}),
        encoding="utf-8",
    )
    loaded = load_manifest(path)
    assert loaded.artifacts[0].filename == "x.whl"
    assert loaded.source_revision is None
    path.write_text(
        json.dumps({"artifacts": [{"filename": "x.whl", "sha256": "nope"}]}),
        encoding="utf-8",
    )
    with pytest.raises(ArtifactError, match="filename and sha256"):
        load_manifest(path)
    with pytest.raises(ArtifactError, match="at least one artifact"):
        build_manifest([], repository="", version="1.0.0", source_revision=None)


def test_manifest_requires_a_bare_digest(tmp_path: Path) -> None:
    # Only the bare hexadecimal spelling is a digest here. An algorithm prefix
    # is what OCI content uses; these are distribution files compared against a
    # package index, which serves bare hex.
    path = tmp_path / "artifacts.json"
    for value in ("sha256:" + "a" * 64, "md5:" + "a" * 64, "A" * 64, "a" * 63):
        path.write_text(
            json.dumps({"artifacts": [{"filename": "x.whl", "sha256": value}]}),
            encoding="utf-8",
        )
        with pytest.raises(ArtifactError, match="filename and sha256"):
            load_manifest(path)


@pytest.mark.parametrize("filename", UNSAFE_MANIFEST_NAMES)
def test_loading_a_manifest_requires_bare_filenames(
    tmp_path: Path, filename: str
) -> None:
    path = tmp_path / "artifacts.json"
    path.write_text(
        json.dumps({"artifacts": [{"filename": filename, "sha256": "0" * 64}]}),
        encoding="utf-8",
    )
    with pytest.raises(ArtifactError, match="unsafe artifact filename"):
        load_manifest(path)


@pytest.mark.parametrize("filename", UNSAFE_MANIFEST_NAMES)
def test_verification_rejects_unsafe_names_in_a_directly_constructed_manifest(
    tmp_path: Path, filename: str
) -> None:
    manifest = Manifest(
        repository="",
        version="",
        source_revision=None,
        created="",
        artifacts=(ManifestEntry(filename, "0" * 64, -1),),
    )
    assert verify_manifest(manifest, tmp_path) == [
        f"unsafe artifact filename {filename!r}: expected a bare file name"
    ]


@pytest.mark.parametrize("second_digest", ["0" * 64, "1" * 64])
def test_loading_a_manifest_rejects_duplicate_filenames(
    tmp_path: Path, second_digest: str
) -> None:
    path = tmp_path / "artifacts.json"
    path.write_text(
        json.dumps(
            {
                "artifacts": [
                    {"filename": "x.whl", "sha256": "0" * 64},
                    {"filename": "x.whl", "sha256": second_digest},
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ArtifactError, match=r"duplicate artifact filename 'x\.whl'"):
        load_manifest(path)


def test_verification_rejects_duplicate_entries_in_a_directly_constructed_manifest(
    tmp_path: Path,
) -> None:
    manifest = build_manifest(
        [wheel(tmp_path)], repository="", version="1.2.3", source_revision=None
    )
    duplicated = replace(manifest, artifacts=manifest.artifacts * 2)
    assert verify_manifest(duplicated, tmp_path) == [
        "duplicate artifact filename 'example-1.2.3-py3-none-any.whl'"
    ]


def test_building_a_manifest_rejects_duplicate_filenames(tmp_path: Path) -> None:
    path = wheel(tmp_path)
    with pytest.raises(ArtifactError, match="duplicate artifact filename"):
        build_manifest([path, path], repository="", version="", source_revision=None)


@POSIX_ONLY
@pytest.mark.parametrize("filename", ["x.whl:stream", r"nested\x.whl"])
def test_building_a_manifest_rejects_names_that_are_not_portable_basenames(
    tmp_path: Path, filename: str
) -> None:
    path = tmp_path / filename
    path.write_bytes(b"artifact")
    with pytest.raises(ArtifactError, match="unsafe artifact filename"):
        build_manifest([path], repository="", version="", source_revision=None)


@POSIX_ONLY
def test_verification_never_hashes_a_symlink_target_outside_the_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = tmp_path / "dist"
    directory.mkdir()
    external = wheel(tmp_path)
    link = directory / external.name
    link.symlink_to(external)
    manifest = build_manifest(
        [link], repository="", version="1.2.3", source_revision=None
    )

    def unexpected_read(path: Path) -> str:
        pytest.fail(f"must not hash a path outside the artifact directory: {path}")

    monkeypatch.setattr("releasing.artifacts.sha256_file", unexpected_read)
    assert verify_manifest(manifest, directory) == [
        f"{link.name}: resolves outside the artifact directory"
    ]


@POSIX_ONLY
def test_verification_accepts_a_symlink_target_inside_the_directory(
    tmp_path: Path,
) -> None:
    target = tmp_path / "payload.bin"
    target.write_bytes(b"validated artifact")
    link = tmp_path / "example-1.2.3.tar.gz"
    link.symlink_to(target.name)
    manifest = build_manifest(
        [link], repository="", version="1.2.3", source_revision=None
    )
    assert verify_manifest(manifest, tmp_path) == []


@POSIX_ONLY
def test_verification_reports_a_broken_symlink_as_missing(tmp_path: Path) -> None:
    link = tmp_path / "x.whl"
    link.symlink_to("missing")
    manifest = Manifest(
        repository="",
        version="",
        source_revision=None,
        created="",
        artifacts=(ManifestEntry(link.name, "0" * 64, -1),),
    )
    assert verify_manifest(manifest, tmp_path) == ["x.whl: missing"]


@POSIX_ONLY
def test_verification_reports_a_symlink_loop_without_raising(tmp_path: Path) -> None:
    link = tmp_path / "x.whl"
    link.symlink_to(link.name)
    manifest = Manifest(
        repository="",
        version="",
        source_revision=None,
        created="",
        artifacts=(ManifestEntry(link.name, "0" * 64, -1),),
    )
    problems = verify_manifest(manifest, tmp_path)
    assert len(problems) == 1
    assert problems[0].startswith("x.whl: cannot resolve artifact:")


def test_manifest_carries_producer_specific_keys(tmp_path: Path) -> None:
    # A gate that implements a versioned guide records which guide revision
    # its evidence belongs to; readers of the standard shape ignore the key.
    files = [wheel(tmp_path)]
    manifest = build_manifest(
        files, repository="foundata/example", version="1.2.3", source_revision="a" * 40
    )
    text = dump_manifest(manifest, extra={"guideRevision": "b" * 40})
    data = json.loads(text)
    assert data["guideRevision"] == "b" * 40
    assert list(data)[-1] == "artifacts"
    (tmp_path / "artifacts.json").write_text(text, encoding="utf-8")
    assert load_manifest(tmp_path / "artifacts.json").artifacts == manifest.artifacts
    with pytest.raises(ArtifactError, match="shadows a standard key"):
        dump_manifest(manifest, extra={"version": "9.9.9"})
    with pytest.raises(ArtifactError, match="JSON-serializable"):
        dump_manifest(manifest, extra={"when": object()})
    with pytest.raises(ArtifactError, match="non-empty strings"):
        dump_manifest(manifest, extra={"": "x"})
