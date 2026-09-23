# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later

import ast
import io
from pathlib import Path
from typing import TextIO

import pytest
from typing_extensions import override

from releasing import reporting

SOURCE = Path(reporting.__file__).parent


class Terminal(io.StringIO):
    """A stream that claims to be a terminal."""

    @override
    def isatty(self) -> bool:
        return True


class Closed(io.StringIO):
    """A stream that refuses the question, as a closed file does."""

    @override
    def isatty(self) -> bool:
        raise ValueError("I/O operation on closed file")


def _first_words(node: ast.AST, assignments: dict[str, list[str]]) -> list[str]:
    """The words a phase argument can begin with, as far as the source shows."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value.split(" ")[0]]
    if isinstance(node, ast.JoinedStr) and node.values:
        first = node.values[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            return [first.value.split(" ")[0]]
        # A verb chosen by a dry run is held in a variable; both of its
        # possible values have to be verbs too.
        if isinstance(first, ast.FormattedValue) and isinstance(first.value, ast.Name):
            return [value.split(" ")[0] for value in assignments[first.value.id]]
    return []


def phase_openings() -> list[tuple[str, int, str]]:
    """Every word the narration can start a line with, found in the source."""
    found: list[tuple[str, int, str]] = []
    for path in sorted(SOURCE.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assignments: dict[str, list[str]] = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            if not isinstance(target, ast.Name):
                continue
            candidates = (
                [node.value.body, node.value.orelse]
                if isinstance(node.value, ast.IfExp)
                else [node.value]
            )
            values = [
                candidate.value
                for candidate in candidates
                if isinstance(candidate, ast.Constant)
                and isinstance(candidate.value, str)
            ]
            if values:
                assignments.setdefault(target.id, []).extend(values)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "phase"
                and node.args
                and not isinstance(node.args[0], ast.Name)
            ):
                for word in _first_words(node.args[0], assignments):
                    found.append((path.name, node.lineno, word))
    return found


def test_every_narrated_line_starts_with_a_known_verb() -> None:
    # The colour is applied by position, and a reader scans the first word of
    # each line, so the vocabulary is closed on purpose.
    openings = phase_openings()

    assert len(openings) >= 25, "the source scan found almost nothing"
    unknown = [
        f"{name}:{line}: {word!r}"
        for name, line, word in openings
        if word not in reporting.VERBS
    ]
    assert not unknown, "not in reporting.VERBS: " + ", ".join(unknown)


@pytest.mark.parametrize(
    ("stream", "environ", "expected"),
    [
        (Terminal(), {}, True),
        (Terminal(), {"NO_COLOR": "1"}, False),
        (Terminal(), {"TERM": "dumb"}, False),
        (Terminal(), {"NO_COLOR": "1", "FORCE_COLOR": "1"}, False),
        (Terminal(), {"NO_COLOR": ""}, True),
        (io.StringIO(), {}, False),
        (io.StringIO(), {"FORCE_COLOR": "1"}, True),
        (Closed(), {}, False),
    ],
    ids=[
        "terminal",
        "no-color",
        "dumb-terminal",
        "no-color-wins",
        "empty-no-color-is-unset",
        "redirected",
        "forced",
        "closed",
    ],
)
def test_colour_follows_the_stream_and_the_conventional_variables(
    stream: io.StringIO,
    environ: dict[str, str],
    expected: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A redirected story is the audit trail of a release; escape sequences in
    # it would be noise in the record. On Windows the last step asks the
    # console itself, which a stream double has no handle for, so that answer
    # is supplied here and the decision under test is the one above it.
    monkeypatch.setattr(reporting, "_enable_windows_sequences", lambda stream: True)

    assert reporting.wants_colour(stream, environ) is expected


def test_a_coloured_line_paints_the_marker_and_the_verb_only() -> None:
    stream = io.StringIO()
    writer = reporting.Writer(stream, colour=True)

    writer.phase("Exporting 1234abcd into a temporary directory")
    writer.phase("Would run: uv build")
    writer.command(["/usr/bin/git", "tag", "-a", "v1.0.0"])

    assert stream.getvalue() == (
        "\033[2m»\033[0m \033[32mExporting\033[0m 1234abcd into a temporary directory\n"
        "\033[2m»\033[0m \033[33mWould\033[0m run: uv build\n"
        "\033[1m$\033[0m git tag -a v1.0.0\n"
    )


@pytest.mark.parametrize(
    ("status", "colour"),
    [(200, "\033[32m"), (404, "\033[33m"), (500, "\033[31m"), ("failed", "\033[31m")],
)
def test_an_answer_is_painted_by_what_it_means(status: int | str, colour: str) -> None:
    # A 404 is how a release starts: no release exists for this tag yet.
    stream = io.StringIO()

    reporting.Writer(stream, colour=True).request("GET", "https://example.test", status)

    assert stream.getvalue().endswith(f"→ {colour}{status}\033[0m\n")


def test_without_colour_the_line_is_exactly_the_plain_text() -> None:
    # Everything that reads this output through a pipe, including the whole
    # test suite, must see no escape sequence at all.
    stream = io.StringIO()
    writer = reporting.Writer(stream, colour=False)

    writer.phase("Prepared README.md")
    writer.command(["/usr/bin/uv", "build"], executed=False)
    writer.request("GET", "https://example.test", 200)

    assert stream.getvalue() == (
        "» Prepared README.md\n"
        "» Would run: uv build\n"
        "» GET https://example.test → 200\n"
    )


@pytest.mark.parametrize(
    ("path", "platform", "expected"),
    [
        ("/usr/bin/git", "linux", "git"),
        ("/usr/bin/git.EXE", "linux", "git.EXE"),
        ("C:/tools/MinGit/cmd/git.EXE", "win32", "git"),
        ("C:/tools/uv/uv.exe", "win32", "uv"),
        ("C:/tools/gh/gh", "win32", "gh"),
        ("C:/tools/notes.txt", "win32", "notes.txt"),
    ],
    ids=[
        "posix",
        "posix-keeps-a-literal-name",
        "exe",
        "lowercase",
        "none",
        "not-a-program",
    ],
)
def test_a_program_is_named_the_way_it_is_typed(
    path: str, platform: str, expected: str
) -> None:
    # A path search on Windows appends the extension it matched, and
    # "git.EXE failed" names a file rather than the command that ran.
    assert reporting.program(path, platform=platform) == expected


def test_a_command_line_is_quoted_the_way_its_platform_expects() -> None:
    argv = ["C:/tools/MinGit/cmd/git.EXE", "tag", "-a", "v1.0.0", "-m", "version 1.0.0"]

    assert reporting.render(argv, platform="win32") == (
        'git tag -a v1.0.0 -m "version 1.0.0"'
    )
    assert reporting.render(["/usr/bin/git", "tag", "-m", "version 1.0.0"]) == (
        "git tag -m 'version 1.0.0'"
    )


def test_a_windows_console_has_the_last_word_on_colour(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A console that will not interpret escape sequences would print them, so
    # a terminal there is not enough on its own.
    asked: list[TextIO] = []

    def refuse(stream: TextIO) -> bool:
        asked.append(stream)
        return False

    monkeypatch.setattr(reporting, "_enable_windows_sequences", refuse)

    assert reporting.wants_colour(Terminal(), {}, platform="win32") is False
    assert len(asked) == 1

    monkeypatch.setattr(reporting, "_enable_windows_sequences", lambda stream: True)
    assert reporting.wants_colour(Terminal(), {}, platform="win32") is True
    # A stream that is no terminal is never asked.
    assert reporting.wants_colour(io.StringIO(), {}, platform="win32") is False
