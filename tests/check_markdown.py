# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later
"""Run the foundata Markdown guide's flags on maintained helper documentation."""

import argparse
import subprocess
from pathlib import Path

RULES = (
    "--no-config",
    "--deny-config-warnings",
    "--extend-enable",
    "MD060,MD070,MD072,MD073,MD080,MD082,MD083,MD084,MD085,MD087,MD088",
    "--config",
    'MD003.style="atx"',
    "--config",
    'MD004.style="dash"',
    "--config",
    "MD007.indent=2",
    "--config",
    "MD012.maximum=3",
    "--config",
    "MD013.line-length=80",
    "--config",
    "MD013.reflow=true",
    "--config",
    'MD013.reflow-mode="default"',
    "--config",
    "MD013.code-blocks=false",
    "--config",
    "MD013.code-spans=false",
    "--config",
    "MD013.tables=false",
    "--config",
    "MD024.siblings-only=true",
    "--config",
    'MD029.style="ordered"',
    "--config",
    'MD033.allowed-elements=["a","br"]',
    "--config",
    'MD046.style="fenced"',
    "--config",
    'MD060.style="aligned"',
    "--config",
    'MD060.column-align-header="center"',
    "--config",
    "MD060.loose-last-column=true",
    "--config",
    "MD082.allow-parent-headings=true",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", action="store_true")
    args = parser.parse_args()
    return subprocess.run(
        [
            "rumdl",
            "fmt" if args.format else "check",
            *RULES,
            "--no-cache",
            "README.md",
            "DEVELOPMENT.md",
            "docs/artifacts.md",
            "docs/build.md",
            "docs/changelog.md",
            "docs/config.md",
            "docs/markdown.md",
            "docs/tag.md",
            "docs/version.md",
            "git-review-unpushed-README.md",
        ],
        cwd=Path(__file__).resolve().parents[1],
        check=False,
        timeout=120,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
