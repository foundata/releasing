# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later
"""Run the suite with every direct runtime dependency at its declared floor."""

import argparse
import subprocess
import sys
import tomllib
from collections.abc import Sequence
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]


def minimum(specifiers: SpecifierSet) -> Version:
    bounds = [
        Version(item.version) for item in specifiers if item.operator in {">=", "=="}
    ]
    if not bounds or max(bounds) not in specifiers:
        raise ValueError(f"an installable inclusive minimum is required: {specifiers}")
    return max(bounds)


def dependency_floors(dependencies: Sequence[str]) -> tuple[str, ...]:
    floors = []
    for value in dependencies:
        requirement = Requirement(value)
        if requirement.url or requirement.marker or requirement.extras:
            raise ValueError(f"a dedicated floor case is required for {value}")
        floors.append(f"{requirement.name}=={minimum(requirement.specifier)}")
    return tuple(floors)


def verify_installed(floors: Sequence[str]) -> None:
    for value in floors:
        requirement = Requirement(value)
        installed = Version(version(requirement.name))
        if installed not in requirement.specifier:
            raise ValueError(f"expected {value}, installed {installed}")
        print(f"{requirement.name}: {installed}", flush=True)


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--verify-and-test", action="store_true", help=argparse.SUPPRESS
    )
    args = parser.parse_args(arguments)
    try:
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
            "project"
        ]
        floors = dependency_floors(project["dependencies"])
        if args.verify_and_test:
            verify_installed(floors)
            command = [sys.executable, "-m", "pytest", "-q"]
        else:
            python = minimum(SpecifierSet(project["requires-python"]))
            command = ["uv", "run", "--locked", "--isolated", "--python", str(python)]
            for requirement in floors:
                command.extend(["--with", requirement])
            command.extend(
                ["python", str(Path(__file__).resolve()), "--verify-and-test"]
            )
        return subprocess.run(command, cwd=ROOT, timeout=1800, check=False).returncode
    except (
        OSError,
        ValueError,
        PackageNotFoundError,
        subprocess.TimeoutExpired,
    ) as exc:
        print(f"Dependency floor check failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
