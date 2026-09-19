# `git-review-unpushed.sh`

`git-review-unpushed.sh` reviews commit messages that exist on the current local
branch but not on its configured remote upstream. It fetches that upstream
branch first, then visits the unpushed commits from oldest to newest. It never
pushes.

For each commit, the helper can:

- Edit the message using the configured Git editor.
- Show the commit's diff against its parent using the configured Git pager.
- Continue to the next commit.
- Abort and restore the original branch.

Changing a message rewrites that commit and every following commit. The helper
therefore refuses to run with a dirty working tree, during another Git history
operation, on a divergent branch, or when the unpushed range contains merges.



## Usage

```sh
./git-review-unpushed.sh
./git-review-unpushed.sh -t /path/to/repository
./git-review-unpushed.sh -t /path/to/repository -u origin/main
```

Options:

- `-t repository`: Local Git repository. The default is the current directory.
- `-u upstream`: Optional comparison ref that narrows the range above the
  freshly fetched upstream. It does not replace upstream verification.
- `-h`: Print command help.

The interactive actions are:

- `e`: Open `git commit --amend --only --allow-empty`, then show the same
  commit again. Only the message should change; empty commits are supported.
- `d`: Show `git diff HEAD^ HEAD --`, then show the same commit again.
- `n`: Accept the current message and continue.
- `a`: Abort the rebase and restore the original branch.

`y` and `yes` are also accepted as aliases for `e`. `q` and `quit` are accepted
as aliases for `a`.

## Required upstream verification

The current branch must have exactly one configured remote upstream branch.
A missing upstream or a local upstream (`branch.NAME.remote = .`) is refused,
even when `-u` is supplied. Configure remote tracking before using this helper.

Every invocation fetches the exact configured upstream branch. A failed fetch,
a deleted remote branch, or an upstream that is not an ancestor of the current
branch blocks review. A stale remote-tracking ref is never used as evidence of
a successful fetch.

By default, review begins immediately after the freshly fetched upstream tip.
An explicit `-u` must name a commit at or after that tip and at or before
`HEAD`. For example, `-u HEAD~2` reviews the last two commits only when both
are unpushed. A local branch, tag or SHA does not enable offline operation.
Ranges that would include published commits are rejected, not silently trimmed.

This verifies publication to the configured upstream as of the fetch. It does
not check other branches or remotes, and cannot prevent another process from
pushing while review is in progress.

## Message and recovery safety

The helper forces unabbreviated rebase commands for its sequence editor and
checks that the number of reviewed commits matches the selected range. A failed
commit display stops review instead of offering acceptance of an unseen message.

Amendment uses message-only mode, and the helper checks both the worktree/index
and the current commit tree before accepting further actions. Do not edit files,
stage changes or run another history operation in the target worktree while the
review is open. Commit hooks still run; hooks that change files or commit
content also stop the review.

Ordinary aborts, display failures, input failures and interruptions restore the
original branch when the review state is clean and its commit tree is unchanged.
If unrelated changes or an unexpected commit tree are detected, the helper exits
with an error and preserves the state instead of automatically aborting. This
also applies when `a` is entered after files have changed.

In that case, inspect `git status` and `git diff --cached`, preserve any work
you need, then finish or abort the rebase manually. Do not run
`git rebase --abort` until you are prepared to discard the changes it would
remove.

## Tests and checks

The regression suite uses temporary repositories, local filesystem remotes and
pseudo-terminals under Dash and Bash. It does not contact your remotes, change
your branch history or push anything:

```sh
uv run --frozen pytest tests/integration/test_git_review.py
```

The [development guide](../DEVELOPMENT.md) lists the shell style checks.



## Git subcommand

Git discovers executables named `git-NAME` in `PATH`. Create a symlink without
the `.sh` suffix and ensure `${HOME}/.local/bin` is in `PATH`:

```sh
mkdir -p "${HOME}/.local/bin"
ln -s /absolute/path/to/git-review-unpushed.sh \
  "${HOME}/.local/bin/git-review-unpushed"
export PATH="${HOME}/.local/bin:${PATH}"
```

The helper can then be called from a repository:

```sh
git review-unpushed
```

Alternatively, configure a Git alias that points directly to the script:

```sh
git config --global alias.review-unpushed \
  '!/absolute/path/to/git-review-unpushed.sh'
```

This also enables:

```sh
git review-unpushed
```
