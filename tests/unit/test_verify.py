# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later

import io
import json
import urllib.error
from email.message import Message
from typing import Any

import pytest
from typing_extensions import override

from releasing import forge_api, verify
from releasing.artifacts import Manifest, ManifestEntry
from releasing.forges import Forge

FORGE = Forge(
    "github",
    "foundata/example",
    "https://github.com",
    "https://raw.githubusercontent.com",
    "https://api.github.com",
)
MANIFEST = Manifest(
    repository="foundata/example",
    version="1.0.0",
    source_revision="a" * 40,
    artifacts=(
        ManifestEntry("example-1.0.0.tar.gz", "1" * 64, 10),
        ManifestEntry("example-1.0.0-py3-none-any.whl", "2" * 64, 20),
    ),
    created="2026-09-20T10:00:00+00:00",
)


class Response(io.BytesIO):
    @override
    def __enter__(self) -> "Response":
        return self

    @override
    def __exit__(self, *_: object) -> None:
        self.close()


def answer(
    monkeypatch: pytest.MonkeyPatch,
    module: Any,
    payload: object,
    *,
    status: int | None = None,
) -> list[str]:
    seen: list[str] = []

    def fake(request: Any, timeout: float = 0) -> Response:
        seen.append(request.full_url)
        if status is not None:
            # A real body: on 3.14 an HTTPError without one opens a temporary
            # file that warns when collected.
            raise urllib.error.HTTPError(
                request.full_url, status, "reason", Message(), io.BytesIO(b"{}")
            )
        return Response(json.dumps(payload).encode())

    monkeypatch.setattr(module.urllib.request, "urlopen", fake)
    return seen


def test_pypi_files_are_read_from_the_published_digests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = answer(
        monkeypatch,
        verify,
        {
            "urls": [
                {"filename": "example-1.0.0.tar.gz", "digests": {"sha256": "1" * 64}},
                {
                    "filename": "example-1.0.0-py3-none-any.whl",
                    "digests": {"sha256": "2" * 64},
                },
            ]
        },
    )
    files = verify.index_files("pypi", "example", "1.0.0")
    assert seen == ["https://pypi.org/pypi/example/1.0.0/json"]
    assert verify.compare_with_manifest(MANIFEST, files) == []


def test_galaxy_files_are_read_from_the_artifact_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = answer(
        monkeypatch,
        verify,
        {"artifact": {"filename": "foundata-linux-1.4.0.tar.gz", "sha256": "3" * 64}},
    )
    files = verify.index_files("galaxy", "foundata.linux", "1.4.0")
    assert "collections/index/foundata/linux/versions/1.4.0/" in seen[0]
    assert files[0].filename == "foundata-linux-1.4.0.tar.gz"


def test_compare_reports_missing_altered_and_unexpected_files() -> None:
    problems = verify.compare_with_manifest(
        MANIFEST,
        [
            verify.IndexFile("example-1.0.0.tar.gz", "9" * 64),
            verify.IndexFile("example-1.0.0-py3.11.whl", "8" * 64),
        ],
    )
    assert (
        "example-1.0.0.tar.gz: published digest differs from the validated file"
        in problems
    )
    assert "example-1.0.0-py3-none-any.whl: not published" in problems
    assert "example-1.0.0-py3.11.whl: published but not in the manifest" in problems


def test_unpublished_version_and_unknown_index(monkeypatch: pytest.MonkeyPatch) -> None:
    answer(monkeypatch, verify, None, status=404)
    with pytest.raises(verify.VerificationError, match="not published"):
        verify.index_files("pypi", "example", "9.9.9")
    with pytest.raises(verify.VerificationError, match="publishes nothing"):
        verify.index_files("none", "example", "1.0.0")


def test_latest_release_tag_and_missing_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = answer(monkeypatch, forge_api, {"tag_name": "v1.0.0"})
    assert verify.latest_tag(FORGE) == "v1.0.0"
    assert seen == ["https://api.github.com/repos/foundata/example/releases/latest"]
    answer(monkeypatch, forge_api, None, status=404)
    assert verify.latest_tag(FORGE) is None
    assert forge_api.release_exists(FORGE, "v1.0.0") is False
    answer(monkeypatch, forge_api, {"tag_name": "v1.0.0"})
    assert forge_api.release_exists(FORGE, "v1.0.0") is True
    answer(monkeypatch, forge_api, None, status=500)
    with pytest.raises(forge_api.ForgeError, match="HTTP 500"):
        verify.latest_tag(FORGE)
