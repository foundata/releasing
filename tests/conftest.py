# SPDX-FileCopyrightText: foundata GmbH <https://foundata.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""What every test may assume about the machine it runs on."""

import pytest

from releasing import forge_api

_THROUGH_TOOL = forge_api._through_tool


@pytest.fixture(autouse=True)
def no_forge_login(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep a developer's own GitHub login and tokens out of every test.

    A forge request tries a token from the environment and the logged-in
    `gh` before it goes anonymous. A test that stubs the anonymous request
    would otherwise reach the real forge through whichever of those this
    machine happens to have.
    """
    for name in ("GH_TOKEN", "GITHUB_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(
        forge_api, "_through_tool", lambda forge, path, url: (False, None)
    )


@pytest.fixture
def forge_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    """Restore the real tool path for the tests that exercise it."""
    monkeypatch.setattr(forge_api, "_through_tool", _THROUGH_TOOL)
