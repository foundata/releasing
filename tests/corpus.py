# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later
"""Refresh the immutable README snapshots and their expected output."""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from releasing.markdown import prepare_markdown


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh-from", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
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
            prepared = prepare_markdown(
                data.decode("utf-8"),
                raw_base=f"https://raw.githubusercontent.com/foundata/{repository.name}/refs/heads/main",
                ui_base=f"https://github.com/foundata/{repository.name}/blob/main",
                simplify=simplify,
                strict=True,
            )
            (
                target / ("expected-simplified.md" if simplify else "expected.md")
            ).write_text(prepared, encoding="utf-8", newline="")
        entries.append(
            {
                "repository": repository.name,
                "revision": revision,
                "matches_committed_readme": data == committed,
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    manifest = {"readmes": entries}
    (destination / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Captured {len(entries)} READMEs and both modes in {destination}")


if __name__ == "__main__":
    main()
