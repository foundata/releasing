# SPDX-FileCopyrightText: foundata GmbH <https://foundata.com>
# SPDX-License-Identifier: GPL-3.0-or-later

import shutil
import tempfile
from pathlib import Path

import pytest

from releasing._artifact_staging import Upload, stage
from releasing.artifacts import ArtifactError, sha256_file
from tests.support import POSIX_ONLY


@pytest.fixture
def upload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Upload:
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    directory = tmp_path / "originals"
    directory.mkdir()
    path = directory / "example.whl"
    path.write_bytes(b"validated bytes")
    return Upload(path, sha256_file(path))


def test_staging_yields_independent_verified_copies(
    upload: Upload, tmp_path: Path
) -> None:
    with stage([upload]) as paths:
        assert len(paths) == 1
        assert paths[0] != upload.path
        assert paths[0].name == upload.path.name
        upload.path.write_bytes(b"changed after staging")
        assert paths[0].read_bytes() == b"validated bytes"
    assert not paths[0].parent.exists()
    assert list(tmp_path.glob("releasing-upload-*")) == []


def test_a_changed_later_file_prevents_any_upload_and_cleans_earlier_copies(
    upload: Upload, tmp_path: Path
) -> None:
    later = upload.path.with_name("later.whl")
    later.write_bytes(b"not the planned bytes")
    with pytest.raises(ArtifactError, match="SHA-256 changed since planning"):
        with stage([upload, Upload(later, upload.sha256)]):
            pytest.fail("no uploader may run until every staged file is verified")
    assert list(tmp_path.glob("releasing-upload-*")) == []


@POSIX_ONLY
def test_a_symlink_swapped_after_planning_cannot_escape(
    upload: Upload, tmp_path: Path
) -> None:
    external = tmp_path / "outside.whl"
    external.write_bytes(b"validated bytes")
    upload.path.unlink()
    upload.path.symlink_to(external)
    with pytest.raises(ArtifactError, match="outside the artifact directory"):
        with stage([upload]):
            pytest.fail("an escaping link must not reach the uploader")
    assert list(tmp_path.glob("releasing-upload-*")) == []


def test_copy_failures_remove_partial_staging(
    upload: Upload, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(shutil, "copyfileobj", refuse)
    with pytest.raises(ArtifactError, match="disk full"):
        with stage([upload]):
            pytest.fail("an incomplete copy must not reach the uploader")
    assert list(tmp_path.glob("releasing-upload-*")) == []


@pytest.mark.parametrize("error", [RuntimeError, KeyboardInterrupt])
def test_uploader_failure_or_cancellation_cleans_staging(
    upload: Upload, tmp_path: Path, error: type[BaseException]
) -> None:
    with pytest.raises(error, match="uploader stopped"):
        with stage([upload]) as paths:
            assert paths[0].is_file()
            raise error("uploader stopped")
    assert list(tmp_path.glob("releasing-upload-*")) == []
