# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest

from releasing import attribution

HUMAN = "Andreas Haerter <ah@foundata.com>"


def commit(
    message: str, *, author: str = HUMAN, committer: str = HUMAN
) -> attribution.Commit:
    return attribution.Commit(
        revision="0" * 40,
        subject=message.splitlines()[0],
        author=author,
        committer=committer,
        message=message,
    )


@pytest.mark.parametrize(
    ("message", "rule"),
    [
        (
            "release: prepare 3.0.0\n\n"
            "Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>",
            attribution.CO_AUTHORED_BY,
        ),
        ("feat: add\n\nco-authored-by: Copilot <copilot@github.com>", "co-authored-by"),
        ("feat: add\n\nAssisted-by: Claude Fable 5", attribution.ASSISTED_BY),
        ("feat: add\n\nassisted-by: anything at all", attribution.ASSISTED_BY),
        (
            "feat: add\n\n🤖 Generated with [Claude Code](https://claude.com/code)",
            attribution.GENERATED_WITH,
        ),
        ("feat: add\n\nGenerated with some tool", attribution.GENERATED_WITH),
    ],
    ids=[
        "today's trailer",
        "copilot",
        "assisted-by",
        "assisted-by-anything",
        "robot-emoji",
        "generated-with",
    ],
)
def test_a_message_that_credits_a_tool_is_found(message: str, rule: str) -> None:
    found = attribution.findings([commit(message)])

    assert [item.rule for item in found] == [rule]


@pytest.mark.parametrize(
    "identity",
    [
        "Claude <noreply@anthropic.com>",
        "Copilot <copilot@github.com>",
        "Copilot <198982749+Copilot@users.noreply.github.com>",
        "devin-ai-integration[bot] <devin@example.invalid>",
    ],
)
def test_a_tool_as_author_or_committer_is_found(identity: str) -> None:
    assert attribution.findings([commit("feat: add", author=identity)])
    assert attribution.findings([commit("feat: add", committer=identity)])


@pytest.mark.parametrize(
    "message",
    [
        "docs: document the Claude integration",
        "feat: support Anthropic's API in the client",
        "chore: bump copilot-cli to 2.0.0",
        "fix: the generator with the broken template",
        "feat: add\n\nCo-authored-by: Jane Doe <jane@example.com>",
        "feat: add\n\nSigned-off-by: Andreas Haerter <ah@foundata.com>",
    ],
    ids=[
        "prose",
        "vendor-api",
        "dependency",
        "near-phrase",
        "human-co-author",
        "sign-off",
    ],
)
def test_ordinary_work_is_not_a_finding(message: str) -> None:
    # A project that writes about these tools, or depends on one, must stay
    # releasable; only identities, trailer values and generator phrases count.
    assert attribution.findings([commit(message)]) == []


def test_a_project_can_allow_one_rule_without_allowing_the_rest() -> None:
    # ansible-docsmith discloses under the Ansible Community Policy for
    # AI-Assisted Contributions and still must not publish the others.
    disclosed = commit("feat: add\n\nAssisted-by: Claude Fable 5")
    credited = commit(
        "feat: add\n\nCo-authored-by: Claude <noreply@anthropic.com>",
    )

    assert attribution.findings([disclosed], allowed=["assisted-by"]) == []
    assert attribution.findings([credited], allowed=["assisted-by"])


def test_every_finding_of_one_commit_is_reported() -> None:
    both = commit(
        "release: prepare 1.0.0\n\n"
        "Co-authored-by: Claude <noreply@anthropic.com>\n"
        "Assisted-by: Claude Fable 5",
        author="Claude <noreply@anthropic.com>",
    )

    found = attribution.findings([both])

    assert [item.rule for item in found] == [
        attribution.IDENTITY,
        attribution.CO_AUTHORED_BY,
        attribution.ASSISTED_BY,
    ]
    assert attribution.describe(found) == [
        "000000000000 release: prepare 1.0.0",
        "  identity: Claude <noreply@anthropic.com>",
        "  co-authored-by: Claude <noreply@anthropic.com>",
        "  assisted-by: Claude Fable 5",
    ]
