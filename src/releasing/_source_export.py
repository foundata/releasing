# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later
"""Export a committed source tree, owning only the temporary Git archive."""

import tarfile
import tempfile
from pathlib import Path, PurePosixPath

from releasing import processes, reporting


class BuildError(RuntimeError):
    """The revision cannot be exported, prepared or built."""

    # Keep the public exception name in tracebacks and serialized exceptions.
    __module__ = "releasing.build"


def export(root: Path, revision: str, destination: Path) -> None:
    """Extract ``revision`` of the repository at ``root`` into ``destination``.

    The caller owns the destination, including any partial extraction left by
    a failure. This function owns and cleans up only its temporary archive.
    """
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="releasing-export-") as value:
        archive = Path(value) / "source.tar"
        reporting.phase(f"exporting {revision[:12]} into a temporary directory")
        processes.git(
            root, "archive", "--format=tar", revision, stdout=archive, echo=True
        )
        try:
            with tarfile.open(archive, mode="r:") as stream:
                members = stream.getmembers()
                for member in members:
                    _safe_member(member.name)
                    if member.issym() or member.islnk():
                        continue
                    if not (member.isfile() or member.isdir()):
                        raise BuildError(f"unsupported archive member {member.name}")
                stream.extractall(destination, members=members, filter="tar")
        except (OSError, tarfile.TarError) as exc:
            raise BuildError(f"cannot extract the exported revision: {exc}") from exc


def _safe_member(name: str) -> None:
    member = PurePosixPath(name)
    if (
        "\x00" in name
        or "\\" in name
        or member.is_absolute()
        or any(part in {"", ".", ".."} for part in member.parts)
    ):
        raise BuildError(f"unsafe archive member {name!r}")
