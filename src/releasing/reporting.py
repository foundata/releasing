# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later
"""What the tool says while it works.

A release is rare and consequential, so the person running one should be able
to see what it did: which commands changed the repository, which requests went
to the forge, and what was decided in between. The narration is also the audit
trail when nobody watched the terminal.

Standard output carries the product, standard error carries the story. A
library caller says nothing at all: the default reporter is silent, and the
command-line layer installs a writer for the duration of one command.
"""

import os
import shlex
import subprocess
import sys
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol, TextIO

# Weight carries hierarchy and hue carries meaning: the marker locates a line,
# the command that changes something stands out, and colour is spent only on
# what a reader must not misread. The prose itself is never recoloured, so it
# stays legible on a light and a dark terminal alike.
_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_RED = "\033[31m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"

# Every narrated line starts with one of these, so a reader scans the first
# word of each line and knows what happened. A participle is work in progress,
# a past tense is work that is done, and "Would" is work a dry run declined.
VERBS = frozenset(
    {
        "Attached",
        "Built",
        "Checked",
        "Checking",
        "Created",
        "Deleted",
        "Exporting",
        "Found",
        "Kept",
        "Matched",
        "Prepared",
        "Published",
        "Pushed",
        "Re-checking",
        "Recorded",
        "Released",
        "Running",
        "Skipped",
        "Uploaded",
        "Verified",
        "Would",
    }
)


class Reporter(Protocol):
    """Receives what a command decides, runs and asks for."""

    def phase(self, text: str) -> None:
        """State what is being done or decided."""

    def command(
        self, argv: Sequence[str], *, cwd: Path | None = None, executed: bool = True
    ) -> None:
        """Report an external command, verbatim enough to paste."""

    def request(self, method: str, url: str, status: int | str) -> None:
        """Report one request to a forge or index."""

    def detail(self, text: str) -> None:
        """Show verbatim output, such as a diff, that carries its own format."""


class Silent:
    """Says nothing. The default, so importing this package stays quiet."""

    def phase(self, text: str) -> None:
        """Discard the phase."""

    def command(
        self, argv: Sequence[str], *, cwd: Path | None = None, executed: bool = True
    ) -> None:
        """Discard the command."""

    def request(self, method: str, url: str, status: int | str) -> None:
        """Discard the request."""

    def detail(self, text: str) -> None:
        """Discard the detail."""


def _hue(status: int | str) -> str:
    """The colour of an answer: as asked, worth noticing, or wrong.

    A 4xx is not painted as a failure because it is frequently the expected
    answer: "no release exists for this tag yet" is how a release starts.
    """
    if isinstance(status, int):
        if 200 <= status < 300:
            return _GREEN
        if 300 <= status < 500:
            return _YELLOW
    return _RED


def wants_colour(stream: TextIO, environ: Mapping[str, str] | None = None) -> bool:
    """Whether ``stream`` should carry ANSI styling.

    Redirected output is the audit trail of a release and stays plain, so the
    terminal decides by default. The two conventional variables override it:
    ``NO_COLOR`` suppresses styling and wins over ``FORCE_COLOR``, which
    demands it where no terminal is detected, such as a CI log viewer.
    """
    env = os.environ if environ is None else environ
    if env.get("NO_COLOR"):
        return False
    if env.get("FORCE_COLOR"):
        return True
    if env.get("TERM") == "dumb":
        return False
    try:
        if not stream.isatty():
            return False
    except (AttributeError, ValueError):
        return False
    if sys.platform == "win32":  # pragma: no cover - exercised on Windows only
        return _enable_windows_sequences(stream)
    return True


def _enable_windows_sequences(stream: TextIO) -> bool:  # pragma: no cover
    """Ask a Windows console to interpret escape sequences, reporting success.

    A console that refuses would print the sequences as text, so anything
    unexpected here means plain output rather than a garbled line.
    """
    import ctypes

    enable_virtual_terminal_processing = 0x0004
    try:
        handle = ctypes.windll.kernel32.GetStdHandle(  # type: ignore[attr-defined]
            -11 if stream.fileno() == 1 else -12
        )
        mode = ctypes.c_uint32()
        if not ctypes.windll.kernel32.GetConsoleMode(  # type: ignore[attr-defined]
            handle, ctypes.byref(mode)
        ):
            return False
        return bool(
            ctypes.windll.kernel32.SetConsoleMode(  # type: ignore[attr-defined]
                handle, mode.value | enable_virtual_terminal_processing
            )
        )
    except (AttributeError, OSError, ValueError):
        return False


class Writer:
    """Narrates to a stream, one line per event.

    ``root`` is the directory a reader assumes; a command running anywhere
    else is preceded by the directory it ran in, because the echoed line
    would otherwise not reproduce.

    ``colour`` decides the styling; by default the stream does.
    """

    def __init__(
        self, stream: TextIO, *, root: Path | None = None, colour: bool | None = None
    ) -> None:
        """Narrate to ``stream``, treating ``root`` as the assumed directory."""
        self._stream = stream
        self._root = None if root is None else root.resolve()
        self._colour = wants_colour(stream) if colour is None else colour

    def phase(self, text: str) -> None:
        """Write one line, its leading verb carrying the colour.

        Every phase is written verb first, so the word to colour is found by
        position rather than by guessing which word in a sentence is the verb.
        """
        word, separator, rest = text.partition(" ")
        hue = _YELLOW if word == "Would" else _GREEN
        self._write(
            f"{self._style('»', _DIM)} {self._style(word, hue)}{separator}{rest}"
        )

    def command(
        self, argv: Sequence[str], *, cwd: Path | None = None, executed: bool = True
    ) -> None:
        """Write the command line, with its directory when that is not the root."""
        if cwd is not None and cwd.resolve() != self._root:
            self.phase(f"Running in {cwd}")
        line = render(argv)
        if executed:
            self._write(f"{self._style('$', _BOLD)} {line}")
        else:
            self.phase(f"Would run: {line}")

    def request(self, method: str, url: str, status: int | str) -> None:
        """Write one request and what it answered."""
        marker = self._style("»", _DIM)
        answer = self._style(str(status), _hue(status))
        self._write(f"{marker} {method} {url} → {answer}")

    def _style(self, text: str, style: str) -> str:
        return f"{style}{text}{_RESET}" if self._colour else text

    def detail(self, text: str) -> None:
        """Write verbatim text, unprefixed, so its own format survives."""
        self._stream.write(text)
        self._stream.flush()

    def _write(self, line: str) -> None:
        self._stream.write(line + "\n")
        self._stream.flush()


# What a Windows path search appends to the name of a program. A reader
# types "git", and a diagnostic that says "git.EXE failed" names a file
# rather than the command that was run.
_PROGRAM_SUFFIXES = frozenset({".bat", ".cmd", ".com", ".exe"})


def program(path: str) -> str:
    """The name to show for an executable, without a platform's suffix."""
    name = Path(path).name
    if sys.platform == "win32" and Path(name).suffix.lower() in _PROGRAM_SUFFIXES:
        return Path(name).stem
    return name


def render(argv: Sequence[str]) -> str:
    """Quote an argument list the way the running platform's shell expects.

    The first element is a resolved absolute path, because every program is
    located before it runs. The line is for a reader, and it stays runnable
    with the plain name, since that is where it was found.
    """
    arguments = [program(argv[0]), *(str(argument) for argument in argv[1:])]
    if sys.platform == "win32":  # pragma: no cover - exercised on Windows only
        return subprocess.list2cmdline(arguments)
    return shlex.join(arguments)


_current: Reporter = Silent()


def current() -> Reporter:
    """The reporter in effect."""
    return _current


@contextmanager
def to(stream: TextIO, *, root: Path | None = None) -> Iterator[Reporter]:
    """Narrate to ``stream`` for the duration of the block, then stop."""
    global _current
    previous = _current
    _current = Writer(stream, root=root)
    try:
        yield _current
    finally:
        _current = previous


def phase(text: str) -> None:
    """State what is being done or decided."""
    _current.phase(text)


def command(
    argv: Sequence[str], *, cwd: Path | None = None, executed: bool = True
) -> None:
    """Report an external command."""
    _current.command(argv, cwd=cwd, executed=executed)


def request(method: str, url: str, status: int | str) -> None:
    """Report one request to a forge or index."""
    _current.request(method, url, status)


def detail(text: str) -> None:
    """Show verbatim output that carries its own format."""
    _current.detail(text)


def _paint(text: str, style: str) -> str:
    return f"{style}{text}{_RESET}" if wants_colour(sys.stderr) else text


def error(message: str, *, problems: Sequence[str] = (), hint: str = "") -> None:
    """Report a failure, listing each problem and how to proceed.

    A failure is not part of the story and does not go through the reporter: a
    command that refuses must say why even under ``--quiet``, and a library
    caller never reaches this because it raises instead.
    """
    print(f"{_paint('Error:', _RED + _BOLD)} {message}", file=sys.stderr)
    for problem in problems:
        print(f"  {problem}", file=sys.stderr)
    if hint:
        print(hint, file=sys.stderr)


def warning(message: str, *, problems: Sequence[str] = ()) -> None:
    """Report something that does not stop the work but must not be missed."""
    print(f"{_paint('WARNING:', _YELLOW)} {message}", file=sys.stderr)
    for problem in problems:
        print(f"  {problem}", file=sys.stderr)
