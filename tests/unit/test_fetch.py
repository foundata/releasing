# SPDX-FileCopyrightText: foundata GmbH <https://foundata.com>
# SPDX-License-Identifier: GPL-3.0-or-later

import io
import json
import urllib.error
import urllib.request
from email.message import Message
from typing import Any

import pytest
from typing_extensions import override

from releasing import fetch

URL = "https://api.example.invalid/releases/latest"


class Response(io.BytesIO):
    status = 200

    @override
    def __enter__(self) -> "Response":
        return self

    @override
    def __exit__(self, *_: object) -> None:
        self.close()


def test_a_request_carries_the_standard_headers_and_any_added_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[Any] = []

    def fake(request: Any, timeout: float = 0) -> Response:
        captured.append(request)
        return Response(json.dumps({"tag_name": "v1.0.0"}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake)

    assert fetch.get(URL, headers={"Authorization": "Bearer secret"}) == {
        "tag_name": "v1.0.0"
    }
    assert captured[0].get_header("Cache-control") == "no-cache"
    assert captured[0].get_header("User-agent") == fetch.USER_AGENT
    assert captured[0].get_header("Authorization") == "Bearer secret"
    assert captured[0].get_method() == "GET"


@pytest.mark.parametrize(
    ("status", "expected"),
    [(404, fetch.NotFoundError), (500, fetch.FetchError)],
    ids=["missing", "broken"],
)
def test_a_refusal_is_reported_by_what_it_means(
    monkeypatch: pytest.MonkeyPatch, status: int, expected: type[Exception]
) -> None:
    # A missing document is an answer a caller acts on; anything else is a
    # failure it cannot interpret.
    def fake(request: Any, timeout: float = 0) -> Response:
        raise urllib.error.HTTPError(
            request.full_url, status, "reason", Message(), io.BytesIO(b"{}")
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake)

    with pytest.raises(expected, match=f"HTTP {status}"):
        fetch.get(URL)


def test_an_unreachable_service_is_a_fetch_error_naming_the_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake(request: Any, timeout: float = 0) -> Response:
        raise urllib.error.URLError("name or service not known")

    monkeypatch.setattr(urllib.request, "urlopen", fake)

    with pytest.raises(fetch.FetchError, match="name or service not known") as failure:
        fetch.get(URL)
    assert URL in str(failure.value)
    assert not isinstance(failure.value, fetch.NotFoundError)


def limited(monkeypatch: pytest.MonkeyPatch) -> None:
    """Refuse every request the way GitHub refuses an exhausted address."""

    def fake(request: Any, timeout: float = 0) -> Response:
        headers = Message()
        headers["x-ratelimit-remaining"] = "0"
        headers["x-ratelimit-reset"] = "1791171258"
        raise urllib.error.HTTPError(
            request.full_url, 403, "rate limit exceeded", headers, io.BytesIO(b"{}")
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake)


def test_a_rate_limit_is_an_http_refusal_with_its_reset_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    limited(monkeypatch)
    with pytest.raises(fetch.RateLimitError) as failure:
        fetch.get(URL)
    assert failure.value.reset is not None
    assert isinstance(failure.value, fetch.FetchError)

    # A 403 that is not about the allowance stays an ordinary refusal.
    def forbidden(request: Any, timeout: float = 0) -> Response:
        raise urllib.error.HTTPError(
            request.full_url, 403, "Forbidden", Message(), io.BytesIO(b"{}")
        )

    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    with pytest.raises(fetch.FetchError) as plain:
        fetch.get(URL)
    assert not isinstance(plain.value, fetch.RateLimitError)
