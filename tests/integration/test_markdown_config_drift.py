# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later

"""The drift tool finds every copy of the guide's .rumdl.toml and judges it."""

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from tests.support import POSIX_ONLY

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
    (root / "guidelines" / "markdown.md").write_text(guide, encoding="utf-8")
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
    (root / "guidelines" / "markdown.md").unlink()

    result = run(shell, root)

    assert result.returncode == 1
    assert "No markdown.md at" in result.stderr
    assert "FOUNDATA_GUIDELINES" in result.stderr


def test_a_directory_without_copies_is_an_error(shell: str, tmp_path: Path) -> None:
    root = fleet(tmp_path)
    (root / "project" / ".rumdl.toml").unlink()
    (root / "skeletons" / "role_default" / ".rumdl.toml.j2").unlink()

    result = run(shell, root)

    assert result.returncode == 1
    assert "No .rumdl.toml below" in result.stderr


@pytest.mark.parametrize(
    "place",
    [
        "tmp/experiment",
        "collections/tmp/experiment",
        "project/.nox/build/tmp/collection",
        "project/.tox/py312",
        "project/.venv/lib",
        "project/node_modules/theme",
    ],
)
def test_scratch_and_generated_directories_are_skipped(
    shell: str, tmp_path: Path, place: str
) -> None:
    # A clone made to try something, or a tool's copy of the project, keeps
    # whatever copy it was made with. Reporting it, or rewriting it with -w,
    # would bury the copies someone maintains.
    root = fleet(tmp_path)
    (root / place).mkdir(parents=True)
    (root / place / ".rumdl.toml").write_text("drifted\n", encoding="utf-8")

    result = run(shell, root)

    assert result.returncode == 0, result.stdout
    assert place not in result.stdout
    assert "2 copy/copies checked, 0 stale" in result.stdout


@pytest.mark.parametrize("given", ["archive", "archive/", "archive//"])
def test_named_directories_are_skipped(shell: str, tmp_path: Path, given: str) -> None:
    root = fleet(tmp_path)
    (root / "archive" / "old").mkdir(parents=True)
    (root / "archive" / "old" / ".rumdl.toml").write_text("drifted\n", encoding="utf-8")

    assert run(shell, root).returncode == 1
    result = run(shell, root, "-x", given)

    assert result.returncode == 0, result.stdout
    assert "archive" not in result.stdout


def test_the_searched_directory_may_be_given_relative_or_with_a_slash(
    shell: str, tmp_path: Path
) -> None:
    root = fleet(tmp_path)
    (root / "tmp").mkdir()
    (root / "tmp" / ".rumdl.toml").write_text("drifted\n", encoding="utf-8")

    result = subprocess.run(
        [shell, str(SCRIPT), "-t", "fleet/"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stdout
    assert "ok    project/.rumdl.toml" in result.stdout


def test_write_mode_rewrites_only_the_stale_copies(shell: str, tmp_path: Path) -> None:
    root = fleet(tmp_path)
    stale = root / "project" / ".rumdl.toml"
    stale.write_text("# an older header\n" + CONFIG, encoding="utf-8")
    current = root / "skeletons" / "role_default" / ".rumdl.toml.j2"
    os.utime(current, (1_000_000_000, 1_000_000_000))
    scratch = root / "tmp" / "experiment"
    scratch.mkdir(parents=True)
    (scratch / ".rumdl.toml").write_text("drifted\n", encoding="utf-8")

    result = run(shell, root, "-w")

    assert result.returncode == 0, result.stderr
    assert "wrote project/.rumdl.toml" in result.stdout
    assert "ok    skeletons/role_default/.rumdl.toml.j2" in result.stdout
    assert "2 copy/copies checked, 1 rewritten" in result.stdout
    assert stale.read_bytes() == CONFIG.encode("utf-8")
    # A copy that already matches is not written, so its timestamp stays.
    assert current.stat().st_mtime == 1_000_000_000
    # Skipped directories are skipped for writing too.
    assert (scratch / ".rumdl.toml").read_text(encoding="utf-8") == "drifted\n"
    assert run(shell, root).returncode == 0


@POSIX_ONLY
def test_write_mode_keeps_the_file_mode(shell: str, tmp_path: Path) -> None:
    root = fleet(tmp_path)
    stale = root / "project" / ".rumdl.toml"
    stale.write_text("drifted\n", encoding="utf-8")
    stale.chmod(0o640)

    assert run(shell, root, "-w").returncode == 0
    assert stat.S_IMODE(stale.stat().st_mode) == 0o640


@POSIX_ONLY
@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root writes through a read-only mode",
)
def test_write_mode_reports_a_copy_it_cannot_write(shell: str, tmp_path: Path) -> None:
    root = fleet(tmp_path)
    locked = root / "project" / ".rumdl.toml"
    locked.write_text("drifted\n", encoding="utf-8")
    locked.chmod(0o444)

    result = run(shell, root, "-w")

    assert result.returncode == 1
    assert "error project/.rumdl.toml" in result.stdout
    assert "1 could not be written" in result.stdout
    assert locked.read_text(encoding="utf-8") == "drifted\n"


# REUSE-IgnoreStart
TAGGED = (
    "# SPDX-FileCopyrightText: foundata GmbH <https://foundata.com>\n"
    "# SPDX-License-Identifier: GPL-3.0-or-later\n\n" + CONFIG
)
# REUSE-IgnoreEnd


def test_license_tag_values_may_differ(shell: str, tmp_path: Path) -> None:
    root = fleet(tmp_path, guide=GUIDE.replace(CONFIG, TAGGED))
    (root / "project" / ".rumdl.toml").write_text(
        TAGGED.replace("GPL-3.0-or-later", "Apache-2.0"), encoding="utf-8"
    )
    (root / "skeletons" / "role_default" / ".rumdl.toml.j2").write_text(
        TAGGED.replace("foundata GmbH <https://foundata.com>", "{{ company }}"),
        encoding="utf-8",
    )
    result = run(shell, root)
    assert result.returncode == 0, result.stdout + result.stderr


def test_write_mode_keeps_a_copys_license_tags(shell: str, tmp_path: Path) -> None:
    root = fleet(tmp_path, guide=GUIDE.replace(CONFIG, TAGGED))
    own = TAGGED.replace("GPL-3.0-or-later", "Apache-2.0")
    stale = root / "project" / ".rumdl.toml"
    stale.write_text(own.replace("80", "100"), encoding="utf-8")
    untagged = root / "skeletons" / "role_default" / ".rumdl.toml.j2"
    untagged.write_text(CONFIG, encoding="utf-8")
    assert run(shell, root, "-w").returncode == 0
    assert stale.read_text(encoding="utf-8") == own
    assert untagged.read_text(encoding="utf-8") == TAGGED


def test_invalid_usage_exits_two(shell: str, tmp_path: Path) -> None:
    root = fleet(tmp_path)

    assert run(shell, root, "-Z").returncode == 2
    assert run(shell, root, "positional").returncode == 2
    assert run(shell, root, "-g").returncode == 2
    for outside in ("", "/", "/etc", "../elsewhere", "a/../b", "./a"):
        assert run(shell, root, "-x", outside).returncode == 2, outside

    helped = run(shell, root, "-h")
    assert helped.returncode == 0
    assert "Usage:" in helped.stdout
