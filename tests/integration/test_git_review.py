# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later

import errno
import os
import pty
import select
import shlex
import shutil
import signal
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "git-review-unpushed.sh"
PROMPT = b"[e]dit, [d]iff, [n]ext, or [a]bort? "
pytestmark = pytest.mark.integration


@dataclass
class Repository:
    work: Path
    remote: Path
    seed: Path
    env: dict[str, str]

    def git(self, *args: str, at: Path | None = None) -> str:
        return subprocess.run(
            ["git", "-C", str(at or self.work), *args],
            env=self.env,
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        ).stdout.strip()

    def commit(self, name: str, *, empty: bool = False, at: Path | None = None) -> str:
        path = at or self.work
        if not empty:
            (path / name).write_text(name + "\n", encoding="utf-8")
            self.git("add", "--", name, at=path)
        self.git("commit", "--allow-empty", "-qm", f"fixture: {name}", at=path)
        return self.git("rev-parse", "HEAD", at=path)

    def publish_fixture(self, oid: str, *, source: Path | None = None) -> None:
        # Populate only the disposable bare remote, without any push command.
        self.git("fetch", "--no-tags", str(source or self.work), "main", at=self.remote)
        self.git("update-ref", "refs/heads/main", oid, at=self.remote)

    def state(self) -> tuple[str, str, str]:
        return (
            self.git("rev-parse", "HEAD"),
            self.git("symbolic-ref", "HEAD"),
            self.git("status", "--porcelain", "--untracked-files=all"),
        )

    def rebase_active(self) -> bool:
        git_dir = Path(self.git("rev-parse", "--absolute-git-dir"))
        return (git_dir / "rebase-merge").exists() or (
            git_dir / "rebase-apply"
        ).exists()

    def editor(self, body: str) -> str:
        path = self.work.parent / "message editor.sh"
        path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
        path.chmod(0o700)
        return shlex.quote(str(path))

    def git_wrapper(self, body: str) -> dict[str, str]:
        directory = self.work.parent / "bin"
        directory.mkdir()
        wrapper = directory / "git"
        real_git = shutil.which("git")
        assert real_git is not None
        wrapper.write_text(
            "#!/bin/sh\n" + body + f'\nexec {shlex.quote(real_git)} "$@"\n',
            encoding="utf-8",
        )
        wrapper.chmod(0o700)
        return {"PATH": str(directory) + os.pathsep + self.env["PATH"]}


@pytest.fixture
def repository(tmp_path: Path) -> Repository:
    env = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    env.update(
        {
            "HOME": str(tmp_path),
            "XDG_CONFIG_HOME": str(tmp_path / "config"),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_ALLOW_PROTOCOL": "file",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_AUTHOR_NAME": "Review Fixture",
            "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
            "GIT_COMMITTER_NAME": "Review Fixture",
            "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
            "GIT_EDITOR": "true",
            "GIT_PAGER": "cat",
            "NO_COLOR": "1",
        }
    )
    fixture = Repository(
        tmp_path / "work tree", tmp_path / "remote.git", tmp_path / "seed", env
    )
    fixture.seed.mkdir()
    fixture.git("init", "-q", "-b", "main", at=fixture.seed)
    fixture.commit("base.txt", at=fixture.seed)
    fixture.git(
        "clone", "-q", "--bare", str(fixture.seed), str(fixture.remote), at=fixture.seed
    )
    fixture.git("clone", "-q", str(fixture.remote), str(fixture.work), at=fixture.seed)
    fixture.git("branch", "base")
    return fixture


@pytest.fixture(params=["dash", "bash"])
def shell(request: pytest.FixtureRequest) -> str:
    name = str(request.param)
    executable = shutil.which(name)
    if executable is None:
        pytest.skip(f"{name} is required for this shell compatibility check")
    return executable


@dataclass(frozen=True)
class Review:
    status: int
    prompts: int
    output: str


def review(
    repository: Repository,
    shell: str,
    answers: Sequence[str] = (),
    *,
    options: Sequence[str] = (),
    env: dict[str, str] | None = None,
    on_prompt: Callable[[int], None] | None = None,
    stop_signal: int | None = None,
    script: Path = SCRIPT,
) -> Review:
    master, slave = pty.openpty()
    process = subprocess.Popen(
        [shell, str(script), "-t", str(repository.work), *options],
        env={**repository.env, **(env or {})},
        stdin=slave,
        stdout=slave,
        stderr=slave,
        start_new_session=True,
    )
    os.close(slave)
    transcript = bytearray()
    prompts = 0
    deadline = time.monotonic() + 20
    try:
        while time.monotonic() < deadline:
            if not select.select([master], [], [], 0.1)[0]:
                continue
            try:
                chunk = os.read(master, 65536)
            except OSError as exc:
                if exc.errno != errno.EIO:
                    raise
                break
            if not chunk:
                break
            transcript.extend(chunk)
            while prompts < transcript.count(PROMPT):
                if on_prompt is not None:
                    on_prompt(prompts)
                if stop_signal is not None:
                    process.send_signal(stop_signal)
                else:
                    answer = answers[prompts] if prompts < len(answers) else "a"
                    os.write(
                        master, (answer if answer == "\x04" else answer + "\n").encode()
                    )
                prompts += 1
        else:
            pytest.fail(f"Review timed out:\n{transcript.decode(errors='replace')}")
        process.wait(timeout=5)
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
        os.close(master)
    return Review(process.returncode, prompts, transcript.decode().replace("\r", ""))


def test_abbreviated_commands_still_review_every_commit(
    repository: Repository, shell: str
) -> None:
    first = repository.commit("first.txt")
    second = repository.commit("second.txt")
    repository.git("config", "rebase.abbreviateCommands", "true")
    before = repository.state()
    result = review(repository, shell, ["n", "n"])
    assert result.status == 0, result.output
    assert result.prompts == 2
    assert result.output.index("commit " + first) < result.output.index(
        "commit " + second
    )
    assert "All unpushed commit messages were reviewed." in result.output
    assert repository.state() == before
    assert not repository.rebase_active()


@pytest.mark.parametrize("empty", [False, True])
def test_reword_changes_only_messages_and_preserves_each_tree(
    repository: Repository, shell: str, empty: bool
) -> None:
    repository.commit("first.txt", empty=empty)
    repository.commit("second.txt")
    before = repository.git("log", "--reverse", "--format=%T", "base..HEAD")
    editor = repository.editor('printf "%s\\n" "fixture: reworded" > "$1"\n')
    result = review(repository, shell, ["e", "n", "n"], env={"GIT_EDITOR": editor})
    assert result.status == 0, result.output
    assert result.prompts == 3
    assert repository.git(
        "log", "--reverse", "--format=%s", "base..HEAD"
    ).splitlines() == [
        "fixture: reworded",
        "fixture: second.txt",
    ]
    assert repository.git("log", "--reverse", "--format=%T", "base..HEAD") == before
    assert not repository.rebase_active()


@pytest.mark.parametrize("action", ["e", "n", "a", "\x04"])
@pytest.mark.parametrize("change", ["staged", "unstaged", "untracked"])
def test_changes_during_prompt_are_not_committed_or_discarded(
    repository: Repository, shell: str, action: str, change: str
) -> None:
    original = repository.commit("first.txt")

    def modify_files(index: int) -> None:
        assert index == 0
        if change == "untracked":
            (repository.work / "unrelated.txt").write_text(
                "keep me\n", encoding="utf-8"
            )
        else:
            (repository.work / "first.txt").write_text("keep me\n", encoding="utf-8")
            if change == "staged":
                repository.git("add", "first.txt")

    result = review(repository, shell, [action], on_prompt=modify_files)
    assert result.status == 1, result.output
    assert "current state was preserved" in result.output
    assert repository.git("rev-parse", "HEAD") == original
    assert repository.git("status", "--porcelain")
    assert repository.rebase_active()
    path = repository.work / ("unrelated.txt" if change == "untracked" else "first.txt")
    assert path.read_text(encoding="utf-8") == "keep me\n"


def test_hook_cannot_silently_change_the_commit_tree(
    repository: Repository, shell: str
) -> None:
    original = repository.commit("first.txt")
    hook = repository.work / ".git/hooks/pre-commit"
    hook.write_text(
        '#!/bin/sh\nprintf "%s\\n" "hook change" > hook.txt\ngit add hook.txt\n',
        encoding="utf-8",
    )
    hook.chmod(0o700)
    result = review(repository, shell, ["e"])
    assert result.status == 1, result.output
    assert "Files changed during review" in result.output
    assert "All unpushed" not in result.output
    assert repository.git("rev-parse", "refs/heads/main") == original
    assert repository.rebase_active()
    assert repository.git("show", "HEAD:hook.txt") == "hook change"


def test_changed_commit_tree_is_detected_even_with_a_clean_index(
    repository: Repository, shell: str
) -> None:
    original = repository.commit("first.txt")

    def change_commit(index: int) -> None:
        assert index == 0
        repository.commit("unexpected.txt")
        assert repository.git("status", "--porcelain") == ""

    result = review(repository, shell, ["n"], on_prompt=change_commit)
    assert result.status == 1, result.output
    assert "commit tree changed" in result.output
    assert repository.git("rev-parse", "refs/heads/main") == original
    assert repository.rebase_active()


def test_incomplete_review_never_reports_success(
    repository: Repository, shell: str
) -> None:
    repository.commit("first.txt")
    before = repository.state()
    env = repository.git_wrapper(
        "for argument; do\n"
        '  if [ "$argument" = --interactive ]; then\n'
        "    export GIT_SEQUENCE_EDITOR=true\n"
        "  fi\n"
        "done\n"
    )
    result = review(repository, shell, env=env)
    assert result.status == 1, result.output
    assert result.prompts == 0
    assert "Reviewed 0 of 1 commits; review is incomplete." in result.output
    assert "All unpushed" not in result.output
    assert repository.state() == before


def test_failed_display_aborts_without_acceptance_prompt(
    repository: Repository, shell: str
) -> None:
    repository.commit("first.txt")
    before = repository.state()
    env = repository.git_wrapper('if [ "${3:-}" = log ]; then exit 73; fi\n')
    result = review(repository, shell, env=env)
    assert result.status == 1, result.output
    assert result.prompts == 0
    assert "Unable to display the current commit." in result.output
    assert "All unpushed" not in result.output
    assert repository.state() == before
    assert not repository.rebase_active()


def test_abort_after_edit_restores_original_history(
    repository: Repository, shell: str
) -> None:
    repository.commit("first.txt")
    repository.commit("second.txt")
    before = repository.state()
    editor = repository.editor('printf "%s\\n" "fixture: temporary" > "$1"\n')
    result = review(repository, shell, ["e", "a"], env={"GIT_EDITOR": editor})
    assert result.status == 1, result.output
    assert "original branch was restored" in result.output
    assert repository.state() == before
    assert not repository.rebase_active()


@pytest.mark.parametrize("dirty", [False, True])
def test_signal_restores_clean_review_but_preserves_new_changes(
    repository: Repository, shell: str, dirty: bool
) -> None:
    repository.commit("first.txt")
    before = repository.state()

    def modify_files(index: int) -> None:
        if dirty:
            (repository.work / "first.txt").write_text("keep me\n", encoding="utf-8")

    result = review(
        repository, shell, on_prompt=modify_files, stop_signal=signal.SIGTERM
    )
    assert result.status == 143, result.output
    if dirty:
        assert repository.rebase_active()
        assert (repository.work / "first.txt").read_text(
            encoding="utf-8"
        ) == "keep me\n"
    else:
        assert repository.state() == before
        assert not repository.rebase_active()


def test_newly_published_commits_are_fetched_and_excluded(
    repository: Repository, shell: str
) -> None:
    published = repository.commit("published.txt")
    repository.publish_fixture(published)
    unpublished = repository.commit("unpublished.txt")
    assert repository.git("rev-parse", "origin/main") != published
    result = review(repository, shell, ["n"])
    assert result.status == 0, result.output
    assert result.prompts == 1
    assert "commit " + unpublished in result.output
    assert "commit " + published not in result.output
    assert repository.git("rev-parse", "origin/main") == published


@pytest.mark.parametrize("comparison", [None, "base"])
@pytest.mark.parametrize("failure", ["unavailable", "deleted"])
def test_failed_upstream_verification_blocks_even_local_comparison(
    repository: Repository, shell: str, comparison: str | None, failure: str
) -> None:
    repository.commit("first.txt")
    before = repository.state()
    if failure == "unavailable":
        repository.git(
            "remote", "set-url", "origin", str(repository.work.parent / "absent")
        )
    else:
        repository.git("update-ref", "-d", "refs/heads/main", at=repository.remote)
    result = review(repository, shell, options=["-u", comparison] if comparison else [])
    assert result.status == 1, result.output
    assert result.prompts == 0
    assert "Unable to fetch the configured upstream" in result.output
    assert repository.state() == before
    assert not repository.rebase_active()


def test_comparison_cannot_include_published_commits(
    repository: Repository, shell: str
) -> None:
    published = repository.commit("published.txt")
    repository.publish_fixture(published)
    repository.commit("unpublished.txt")
    before = repository.state()
    result = review(repository, shell, options=["-u", "base"])
    assert result.status == 1, result.output
    assert "comparison ref would include published commits" in result.output
    assert result.prompts == 0
    assert repository.state() == before


@pytest.mark.parametrize("kind", ["branch", "tag", "sha"])
def test_comparison_can_narrow_but_not_skip_upstream_fetch(
    repository: Repository, shell: str, kind: str
) -> None:
    first = repository.commit("first.txt")
    comparison = first
    if kind != "sha":
        repository.git(kind, "narrow")
        comparison = "narrow"
    second = repository.commit("second.txt")
    result = review(repository, shell, ["n"], options=["-u", comparison])
    assert result.status == 0, result.output
    assert "Fetching upstream" in result.output
    assert result.prompts == 1
    assert "commit " + second in result.output
    assert "commit " + first not in result.output


@pytest.mark.parametrize("configuration", ["missing", "local", "multiple"])
def test_explicit_comparison_does_not_replace_required_remote_upstream(
    repository: Repository, shell: str, configuration: str
) -> None:
    repository.commit("first.txt")
    before = repository.state()
    if configuration == "missing":
        repository.git("config", "--unset", "branch.main.remote")
    elif configuration == "local":
        repository.git("config", "branch.main.remote", ".")
    else:
        repository.git("config", "--add", "branch.main.merge", "refs/heads/other")
    result = review(repository, shell, options=["-u", "base"])
    assert result.status == 1, result.output
    assert result.prompts == 0
    assert repository.state() == before
    assert not repository.rebase_active()


def test_divergent_actual_upstream_blocks_local_comparison(
    repository: Repository, shell: str
) -> None:
    remote_commit = repository.commit("remote-only.txt", at=repository.seed)
    repository.publish_fixture(remote_commit, source=repository.seed)
    repository.commit("local-only.txt")
    before = repository.state()
    result = review(repository, shell, options=["-u", "base"])
    assert result.status == 1, result.output
    assert "freshly fetched upstream is not an ancestor" in result.output
    assert repository.state() == before


def test_no_unpushed_commits_still_fetches(repository: Repository, shell: str) -> None:
    result = review(repository, shell)
    assert result.status == 0, result.output
    assert result.prompts == 0
    assert "Fetching upstream" in result.output
    assert "No unpushed commits" in result.output


def test_custom_fetch_mapping_does_not_use_stale_conventional_tracking_ref(
    repository: Repository, shell: str
) -> None:
    published = repository.commit("published.txt")
    repository.publish_fixture(published)
    repository.commit("unpublished.txt")
    repository.git("config", "remote.origin.fetch", "+refs/heads/*:refs/custom/*")
    result = review(repository, shell, ["n"])
    assert result.status == 0, result.output
    assert result.prompts == 1
    assert repository.git("rev-parse", "origin/main") != published
    assert repository.git("rev-parse", "refs/custom/main") == published


def test_helper_path_with_shell_metacharacters(
    repository: Repository, shell: str
) -> None:
    repository.commit("first.txt")
    alias = repository.work.parent / "review 'quoted' $name.sh"
    alias.symlink_to(SCRIPT)
    result = review(repository, shell, ["n"], script=alias)
    assert result.status == 0, result.output
    assert result.prompts == 1


def test_initial_dirty_state_is_refused_before_fetching(
    repository: Repository, shell: str
) -> None:
    repository.commit("first.txt")
    (repository.work / "untracked.txt").write_text("keep me\n", encoding="utf-8")
    before = repository.state()
    result = review(repository, shell)
    assert result.status == 1, result.output
    assert "working tree must be clean" in result.output
    assert "Fetching upstream" not in result.output
    assert repository.state() == before


def test_diff_and_failed_editor_leave_commit_unchanged(
    repository: Repository, shell: str
) -> None:
    repository.commit("first.txt")
    before = repository.state()
    result = review(repository, shell, ["d", "e", "n"], env={"GIT_EDITOR": "false"})
    assert result.status == 0, result.output
    assert result.prompts == 3
    assert "diff --git a/first.txt b/first.txt" in result.output
    assert "The commit message was not changed." in result.output
    assert repository.state() == before


def test_clean_input_failure_restores_original_branch(
    repository: Repository, shell: str
) -> None:
    repository.commit("first.txt")
    before = repository.state()
    result = review(repository, shell, ["\x04"])
    assert result.status == 1, result.output
    assert "Unable to read a response." in result.output
    assert repository.state() == before
    assert not repository.rebase_active()


def test_linked_worktree_abort_uses_its_own_rebase_state(
    repository: Repository, shell: str
) -> None:
    worktree = repository.work.parent / "linked tree"
    repository.git("worktree", "add", "-b", "review", str(worktree))
    repository.git("config", "branch.review.remote", "origin")
    repository.git("config", "branch.review.merge", "refs/heads/main")
    linked = Repository(worktree, repository.remote, repository.seed, repository.env)
    linked.commit("first.txt")
    before = linked.state()
    original = repository.state()
    editor = linked.editor('printf "%s\\n" "fixture: edited" > "$1"\n')
    result = review(linked, shell, ["e", "a"], env={"GIT_EDITOR": editor})
    assert result.status == 1, result.output
    assert "original branch was restored" in result.output
    assert linked.state() == before
    assert repository.state() == original
    assert not linked.rebase_active()
