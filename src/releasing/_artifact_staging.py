# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later
"""Own the verified copies handed to external upload tools."""

import shutil
import tempfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from releasing.artifacts import ArtifactError, sha256_file


@dataclass(frozen=True)
class Upload:
    """A source path anchored at planning time and the digest it must retain."""

    path: Path
    sha256: str


@contextmanager
def stage(uploads: Sequence[Upload]) -> Iterator[tuple[Path, ...]]:
    """Copy and verify every input before yielding any paths to an uploader."""
    if not uploads:
        yield ()
        return
    if len({item.path.name for item in uploads}) != len(uploads):
        raise ArtifactError("upload file names must be unique")
    try:
        with tempfile.TemporaryDirectory(prefix="releasing-upload-") as value:
            directory = Path(value)
            staged = []
            for item in uploads:
                try:
                    source = item.path.resolve(strict=True)
                except RuntimeError as exc:
                    raise ArtifactError(f"cannot resolve {item.path}: {exc}") from exc
                if not source.is_relative_to(item.path.parent.resolve()):
                    raise ArtifactError(
                        f"{item.path.name}: resolves outside the artifact directory"
                    )
                if not source.is_file():
                    raise ArtifactError(f"{item.path.name}: not a regular file")
                target = directory / item.path.name
                with source.open("rb") as reader, target.open("xb") as writer:
                    shutil.copyfileobj(reader, writer)
                if sha256_file(target) != item.sha256:
                    raise ArtifactError(
                        f"{item.path.name}: SHA-256 changed since planning; upload refused"
                    )
                staged.append(target)
            yield tuple(staged)
    except OSError as exc:
        raise ArtifactError(f"cannot stage upload files: {exc}") from exc
