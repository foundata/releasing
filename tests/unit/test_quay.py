# SPDX-FileCopyrightText: foundata GmbH <https://foundata.com>
# SPDX-License-Identifier: GPL-3.0-or-later

import io
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest
from typing_extensions import override

from releasing import quay, reporting
from tests.support import POSIX_ONLY, FakeQuay

API = "https://quay.example/api/v1"
REPOSITORY = quay.Repository("quay.example", "acme", "tool")
URL = API + "/repository/acme/tool"
PREPARED = quay.Description("0" * 40, "README.md", "# Tool\n\nNew text.\n")


class Response(io.BytesIO):
    status = 200

    @override
    def __enter__(self) -> "Response":
        return self

    @override
    def __exit__(self, *_: object) -> None:
        self.close()


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


def test_a_token_is_read_without_its_line_ending(token_file: Path) -> None:
    assert quay.read_token(token_file) == "secret-token"


@pytest.mark.parametrize("content", [b"", b"\n", b"two tokens\n", b"a\x00b", b"\xff"])
def test_a_file_without_exactly_one_token_is_refused(
    tmp_path: Path, content: bytes
) -> None:
    path = tmp_path / "quay.token"
    path.write_bytes(content)
    path.chmod(0o600)
    with pytest.raises(quay.QuayError, match="token file"):
        quay.read_token(path)


def test_a_missing_or_oversized_token_file_is_refused(tmp_path: Path) -> None:
    with pytest.raises(quay.QuayError, match="cannot open the token file"):
        quay.read_token(tmp_path / "absent")
    path = tmp_path / "quay.token"
    path.write_bytes(b"x" * (quay.MAX_TOKEN_BYTES + 1))
    path.chmod(0o600)
    with pytest.raises(quay.QuayError, match="too large"):
        quay.read_token(path)


@POSIX_ONLY
def test_a_token_file_others_may_read_is_refused(token_file: Path) -> None:
    token_file.chmod(0o640)
    with pytest.raises(quay.QuayError, match="chmod 600"):
        quay.read_token(token_file)


@POSIX_ONLY
def test_a_token_file_that_is_a_link_or_no_file_is_refused(
    tmp_path: Path, token_file: Path
) -> None:
    link = tmp_path / "link.token"
    link.symlink_to(token_file)
    with pytest.raises(quay.QuayError, match="symbolic link"):
        quay.read_token(link)
    directory = tmp_path / "directory.token"
    directory.mkdir(mode=0o700)
    with pytest.raises(quay.QuayError, match="not a regular file"):
        quay.read_token(directory)


@POSIX_ONLY
def test_a_token_file_of_another_user_is_refused(
    monkeypatch: pytest.MonkeyPatch, token_file: Path
) -> None:
    monkeypatch.setattr(os, "getuid", lambda: token_file.stat().st_uid + 1)
    with pytest.raises(quay.QuayError, match="does not belong to you"):
        quay.read_token(token_file)


def test_repositories_are_named_with_the_host_the_api_serves() -> None:
    repository = quay.parse_repository("Quay.Example/acme/tool", API)
    assert repository == REPOSITORY
    assert str(repository) == "quay.example/acme/tool"
    assert repository.page_url() == "https://quay.example/repository/acme/tool"
    with pytest.raises(ValueError, match=r"does not serve quay\.io"):
        quay.parse_repository("quay.io/acme/tool", API)


@pytest.mark.parametrize(
    "value",
    [
        "acme/tool",
        "quay.example/acme",
        "quay.example/a/b/c",
        "quay.example/Acme/tool",
        "quay.example/acme/to%6fl",
    ],
)
def test_malformed_repository_names_are_refused(value: str) -> None:
    with pytest.raises(ValueError, match="HOST/NAMESPACE/NAME"):
        quay.parse_repository(value, API)


@pytest.mark.parametrize(
    "value",
    [
        "http://quay.example/api/v1",
        "https://user:secret@quay.example/api/v1",
        "https://quay.example/api/v1?x=1",
        "https://quay.example/api/v1#x",
        "https:///api/v1",
    ],
)
def test_the_api_url_must_be_plain_https(value: str) -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        quay.api_url(value)
    assert quay.api_url("https://quay.example/api/v1/") == API


def test_publishing_writes_with_the_token_and_reads_the_description_back(
    fake: FakeQuay, token_file: Path
) -> None:
    quay.publish(PREPARED, [REPOSITORY], api=API, token_file=token_file)
    assert fake.methods() == ["GET", "PUT", "GET"]
    put = fake.requests[1]
    assert put.full_url == URL
    assert put.get_header("Authorization") == "Bearer secret-token"
    assert put.get_header("Content-type") == "application/json"
    assert json.loads(put.data) == {"description": PREPARED.text}
    assert fake.stored == {URL: PREPARED.text}


def test_a_current_description_is_not_written_again(
    fake: FakeQuay, token_file: Path
) -> None:
    fake.initial = PREPARED.text
    quay.publish(PREPARED, [REPOSITORY, REPOSITORY], api=API, token_file=token_file)
    assert fake.methods() == ["GET", "GET"]


def test_a_dry_run_reads_anonymously_and_shows_the_difference(fake: FakeQuay) -> None:
    stream = io.StringIO()
    with reporting.to(stream):
        quay.publish(PREPARED, [REPOSITORY], api=API, token_file=None, dry_run=True)
    assert fake.methods() == ["GET"]
    assert fake.requests[0].get_header("Authorization") is None
    narration = stream.getvalue()
    assert "+New text." in narration
    assert "-old" in narration
    assert "Would publish the description of quay.example/acme/tool" in narration


def test_an_empty_description_counts_as_text(fake: FakeQuay, token_file: Path) -> None:
    fake.initial = None
    quay.publish(PREPARED, [REPOSITORY], api=API, token_file=token_file)
    assert fake.methods() == ["GET", "PUT", "GET"]


def test_a_write_without_a_token_is_refused(fake: FakeQuay) -> None:
    with pytest.raises(quay.QuayError, match="needs a token file"):
        quay.publish(PREPARED, [REPOSITORY], api=API, token_file=None)
    assert fake.methods() == ["GET"]


def test_a_description_quay_does_not_keep_fails(
    fake: FakeQuay, token_file: Path
) -> None:
    fake.ignore_writes = True
    with pytest.raises(quay.QuayError, match="stores a different description"):
        quay.publish(PREPARED, [REPOSITORY], api=API, token_file=token_file)


def test_an_unanswered_write_is_settled_by_reading_back(
    fake: FakeQuay, token_file: Path
) -> None:
    fake.unanswered_puts = 1
    quay.publish(PREPARED, [REPOSITORY], api=API, token_file=token_file)
    assert fake.methods() == ["GET", "PUT", "GET"]

    fake.stored.clear()
    fake.unanswered_puts = 1
    fake.ignore_writes = True
    with pytest.raises(quay.QuayError, match="got no answer"):
        quay.publish(PREPARED, [REPOSITORY], api=API, token_file=token_file)


@pytest.mark.parametrize(
    ("method", "code", "message"),
    [
        ("GET", 401, "did not accept the token .*OAuth application token"),
        ("GET", 403, "repo:write scope"),
        ("GET", 404, "no such repository"),
        ("PUT", 400, "refused the description .*: Spam suspected; .*for spam"),
        ("GET", 500, "HTTP 500: Spam suspected"),
    ],
)
def test_refusals_say_what_quay_needs(
    fake: FakeQuay, token_file: Path, method: str, code: int, message: str
) -> None:
    fake.refuse[method] = (code, {"detail": "Spam  suspected"})
    with pytest.raises(quay.QuayError, match=message) as error:
        quay.publish(PREPARED, [REPOSITORY], api=API, token_file=token_file)
    assert "secret-token" not in str(error.value)


@pytest.mark.parametrize(
    "answer", [b"not json", b"[]", b'{"name": "tool"}', b'{"description": 1}']
)
def test_an_unexpected_answer_fails(
    monkeypatch: pytest.MonkeyPatch, answer: bytes
) -> None:
    monkeypatch.setattr(
        urllib.request, "urlopen", lambda request, timeout=0: Response(answer)
    )
    with pytest.raises(quay.QuayError, match="Quay"):
        quay.publish(PREPARED, [REPOSITORY], api=API, token_file=None, dry_run=True)


def test_an_unreachable_quay_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    def unreachable(request: Any, timeout: float = 0) -> Response:
        raise urllib.error.URLError("no route to host")

    monkeypatch.setattr(urllib.request, "urlopen", unreachable)
    with pytest.raises(quay.QuayError, match="no route to host"):
        quay.publish(PREPARED, [REPOSITORY], api=API, token_file=None, dry_run=True)
