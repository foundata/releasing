# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later
"""Refresh immutable README snapshots and shell baselines from local repositories."""

import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh-from", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    shell = root / "release-prepare-markdown.sh"
    destination = root / "tests" / "fixtures" / "corpus"
    repositories = sorted(
        [
            args.refresh_from / name
            for name in ("conclear", "ansible-docsmith", "scanmole")
        ]
        + list(args.refresh_from.glob("oci-*-itt"))
    )
    entries = []
    for repository in repositories:
        data = (repository / "README.md").read_bytes()
        revision = subprocess.run(
            ["git", "-C", str(repository), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        committed = subprocess.run(
            ["git", "-C", str(repository), "show", f"{revision}:README.md"],
            check=True,
            capture_output=True,
            timeout=10,
        ).stdout
        target = destination / repository.name
        target.mkdir(parents=True, exist_ok=True)
        (target / "README.md").write_bytes(data)
        for simplify in (False, True):
            with tempfile.TemporaryDirectory(prefix="markdown-baseline-") as value:
                temporary = Path(value) / "README.md"
                temporary.write_bytes(data)
                subprocess.run(
                    [
                        "bash",
                        str(shell),
                        "-o",
                        "foundata",
                        "-r",
                        repository.name,
                        "-b",
                        "main",
                        *(["-s"] if simplify else []),
                        str(temporary),
                    ],
                    check=True,
                    capture_output=True,
                    timeout=30,
                )
                (
                    target / ("shell-simplified.md" if simplify else "shell.md")
                ).write_bytes(temporary.read_bytes())
        entries.append(
            {
                "repository": repository.name,
                "revision": revision,
                "matches_committed_readme": data == committed,
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    manifest = {
        "shell_sha256": hashlib.sha256(shell.read_bytes()).hexdigest(),
        "readmes": entries,
    }
    (destination / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Captured {len(entries)} READMEs and both shell modes in {destination}")


if __name__ == "__main__":
    main()
