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

import shlex
import subprocess
import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol, TextIO


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


class Writer:
    """Narrates to a stream, one line per event.

    ``root`` is the directory a reader assumes; a command running anywhere
    else is preceded by the directory it ran in, because the echoed line
    would otherwise not reproduce.
    """

    def __init__(self, stream: TextIO, *, root: Path | None = None) -> None:
        """Narrate to ``stream``, treating ``root`` as the assumed directory."""
        self._stream = stream
        self._root = None if root is None else root.resolve()

    def phase(self, text: str) -> None:
        """Write one prose line."""
        self._write(f"» {text}")

    def command(
        self, argv: Sequence[str], *, cwd: Path | None = None, executed: bool = True
    ) -> None:
        """Write the command line, with its directory when that is not the root."""
        if cwd is not None and cwd.resolve() != self._root:
            self.phase(f"in {cwd}")
        line = render(argv)
        self._write(f"$ {line}" if executed else f"» would run: {line}")

    def request(self, method: str, url: str, status: int | str) -> None:
        """Write one request and what it answered."""
        self._write(f"» {method} {url} → {status}")

    def detail(self, text: str) -> None:
        """Write verbatim text, unprefixed, so its own format survives."""
        self._stream.write(text)
        self._stream.flush()

    def _write(self, line: str) -> None:
        self._stream.write(line + "\n")
        self._stream.flush()


def render(argv: Sequence[str]) -> str:
    """Quote an argument list the way the running platform's shell expects.

    The first element is a resolved absolute path, because every program is
    located before it runs. The line is for a reader, and it stays runnable
    with the plain name, since that is where it was found.
    """
    arguments = [Path(argv[0]).name, *(str(argument) for argument in argv[1:])]
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


def error(message: str, *, problems: Sequence[str] = ()) -> None:
    """Report a failure, listing each problem below it.

    A failure is not part of the story and does not go through the reporter: a
    command that refuses must say why even under ``--quiet``, and a library
    caller never reaches this because it raises instead.
    """
    print(f"Error: {message}", file=sys.stderr)
    for problem in problems:
        print(f"  {problem}", file=sys.stderr)


def warning(message: str) -> None:
    """Report something that does not stop the work but must not be missed."""
    print(f"WARNING: {message}", file=sys.stderr)
