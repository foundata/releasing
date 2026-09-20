# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later

import io
import json
import tarfile
import zipfile
from pathlib import Path

import pytest

from releasing.artifacts import (
    ArtifactError,
    build_manifest,
    check,
    dump_manifest,
    inspect,
    load_manifest,
    sha256_file,
    verify_manifest,
)

HEADERS = (
    "Metadata-Version: 2.4\nName: example\nVersion: 1.2.3\n"
    "Description-Content-Type: text/markdown\n"
)
LINK = "[docs](https://example.test/)"


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


def test_manifest_accepts_an_algorithm_prefixed_digest(tmp_path: Path) -> None:
    # ConClear's release gate writes "sha256:<hex>"; both spellings name the
    # same digest, and verification compares against the bare hex.
    path = tmp_path / "artifacts.json"
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "artifacts": [{"filename": "x.whl", "sha256": "sha256:" + "a" * 64}],
            }
        ),
        encoding="utf-8",
    )
    assert load_manifest(path).artifacts[0].sha256 == "a" * 64
    path.write_text(
        json.dumps({"artifacts": [{"filename": "x.whl", "sha256": "md5:" + "a" * 64}]}),
        encoding="utf-8",
    )
    with pytest.raises(ArtifactError, match="filename and sha256"):
        load_manifest(path)


def test_prefixed_and_bare_digests_verify_the_same_files(tmp_path: Path) -> None:
    built = sdist(tmp_path)
    manifest = tmp_path / "artifacts.json"
    manifest.write_text(
        json.dumps(
            {
                "artifacts": [
                    {"filename": built.name, "sha256": "sha256:" + sha256_file(built)}
                ]
            }
        ),
        encoding="utf-8",
    )
    assert verify_manifest(load_manifest(manifest), tmp_path) == []
