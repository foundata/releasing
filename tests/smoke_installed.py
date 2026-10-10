# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later
"""Exercise artifact checks through an installed command outside the checkout."""

import argparse
import os
import subprocess
import tempfile
import zipfile
from collections.abc import Sequence
from pathlib import Path


def check_artifacts(
    command: Path, version: str, files: Sequence[Path], cwd: Path
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    for name in ("PYTHONPATH", "PYTHONHOME"):
        environment.pop(name, None)
    return subprocess.run(
        [
            str(command),
            "artifacts",
            "check",
            "--version",
            version,
            *(str(path) for path in files),
        ],
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", type=Path)
    parser.add_argument("version")
    parser.add_argument("files", type=Path, nargs="+")
    args = parser.parse_args()
    command = args.command.resolve()
    files = [path.resolve() for path in args.files]
    with tempfile.TemporaryDirectory(prefix="releasing-installed-smoke-") as value:
        root = Path(value)
        accepted = check_artifacts(command, args.version, files, root)
        assert accepted.returncode == 0, accepted.stdout + accepted.stderr
        assert accepted.stderr == "", accepted.stderr
        lines = accepted.stdout.splitlines()
        assert len(lines) == len(files), accepted.stdout
        for path, line in zip(files, lines, strict=True):
            assert line.startswith(f"{path.name}: "), accepted.stdout
        print(accepted.stdout, end="")

        rejected = root / f"invalid-{args.version}-py3-none-any.whl"
        with zipfile.ZipFile(rejected, "w") as archive:
            archive.writestr(
                f"invalid-{args.version}.dist-info/METADATA",
                f"Metadata-Version: 2.4\nName: invalid\nVersion: {args.version}\n"
                "Description-Content-Type: text/markdown\n\n"
                "# Invalid\n\n[guide](./guide.md)\n",
            )
        refused = check_artifacts(command, args.version, [rejected], root)
        assert refused.returncode == 1, refused.stdout + refused.stderr
        assert refused.stdout == "", refused.stdout
        assert rejected.name in refused.stderr, refused.stderr
        assert "relative destination" in refused.stderr, refused.stderr
        assert "'./guide.md'" in refused.stderr, refused.stderr
        assert "Traceback" not in refused.stderr, refused.stderr
        print("Rejected the wheel with a relative README link")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
