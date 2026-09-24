# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later

"""The drift tool finds every copy of the guide's .rumdl.toml and judges it."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "markdown-config-drift.sh"
pytestmark = pytest.mark.integration

CONFIG = "[MD013]\nline-length = 80\n"
GUIDE = f"""# Markdown style guide

## Linting and automatic formatting<a id="linting"></a>

Run it like this:

```sh
rumdl check --config .rumdl.toml --deny-config-warnings .
```

```toml
{CONFIG}```

Reasoning follows.
"""


@pytest.fixture(params=["dash", "bash", "sh"])
def shell(request: pytest.FixtureRequest) -> str:
    """Every shell the script claims to support, skipping the absent ones."""
    name = str(request.param)
    found = shutil.which(name)
    if found is None:
        pytest.skip(f"no {name} on PATH")
    return found


def fleet(tmp_path: Path, *, guide: str = GUIDE) -> Path:
    """A directory of repositories, one copy each, plus litter to ignore."""
    root = tmp_path / "fleet"
    (root / "guidelines").mkdir(parents=True)
    (root / "guidelines" / "markdown-style-guide.md").write_text(
        guide, encoding="utf-8"
    )
    (root / "project").mkdir()
    (root / "project" / ".rumdl.toml").write_text(CONFIG, encoding="utf-8")
    (root / "skeletons" / "role_default").mkdir(parents=True)
    (root / "skeletons" / "role_default" / ".rumdl.toml.j2").write_text(
        CONFIG, encoding="utf-8"
    )
    # A .git directory is pruned, so a copy Git happens to keep is not a finding.
    (root / "project" / ".git").mkdir()
    (root / "project" / ".git" / ".rumdl.toml").write_text(
        "drifted\n", encoding="utf-8"
    )
    return root


def run(shell: str, root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [shell, str(SCRIPT), "-t", str(root), *arguments],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_matching_copies_are_reported_and_accepted(shell: str, tmp_path: Path) -> None:
    result = run(shell, fleet(tmp_path))

    assert result.returncode == 0, result.stderr
    assert "ok    project/.rumdl.toml" in result.stdout
    assert "ok    skeletons/role_default/.rumdl.toml.j2" in result.stdout
    assert "2 copy/copies checked, 0 stale" in result.stdout
    # The pruned .git copy differs; finding it would make every clone a finding.
    assert ".git" not in result.stdout


def test_a_drifted_copy_fails_and_is_named(shell: str, tmp_path: Path) -> None:
    root = fleet(tmp_path)
    (root / "project" / ".rumdl.toml").write_text(
        CONFIG + "\n# local tweak\n", encoding="utf-8"
    )

    result = run(shell, root)

    assert result.returncode == 1
    assert "stale project/.rumdl.toml" in result.stdout
    assert "ok    skeletons/role_default/.rumdl.toml.j2" in result.stdout
    assert "2 copy/copies checked, 1 stale" in result.stdout


def test_one_byte_of_drift_is_enough(shell: str, tmp_path: Path) -> None:
    # A comparison that normalized whitespace would accept a reflowed copy,
    # which is how the arguments drifted before the file existed.
    root = fleet(tmp_path)
    (root / "project" / ".rumdl.toml").write_text(
        CONFIG.replace("line-length = 80", "line-length  = 80"), encoding="utf-8"
    )

    result = run(shell, root)

    assert result.returncode == 1
    assert "stale project/.rumdl.toml" in result.stdout


def test_a_guide_without_the_block_is_an_error(shell: str, tmp_path: Path) -> None:
    root = fleet(tmp_path, guide="# Guide\n\n## Linting and automatic formatting\n")

    result = run(shell, root)

    assert result.returncode == 1
    assert "No .rumdl.toml block" in result.stderr


def test_a_missing_guide_names_the_override(shell: str, tmp_path: Path) -> None:
    root = fleet(tmp_path)
    (root / "guidelines" / "markdown-style-guide.md").unlink()

    result = run(shell, root)

    assert result.returncode == 1
    assert "No markdown-style-guide.md at" in result.stderr
    assert "FOUNDATA_GUIDELINES" in result.stderr


def test_a_directory_without_copies_is_an_error(shell: str, tmp_path: Path) -> None:
    root = fleet(tmp_path)
    (root / "project" / ".rumdl.toml").unlink()
    (root / "skeletons" / "role_default" / ".rumdl.toml.j2").unlink()

    result = run(shell, root)

    assert result.returncode == 1
    assert "No .rumdl.toml below" in result.stderr


def test_invalid_usage_exits_two(shell: str, tmp_path: Path) -> None:
    root = fleet(tmp_path)

    assert run(shell, root, "-Z").returncode == 2
    assert run(shell, root, "positional").returncode == 2
    assert run(shell, root, "-g").returncode == 2

    helped = run(shell, root, "-h")
    assert helped.returncode == 0
    assert "Usage:" in helped.stdout
