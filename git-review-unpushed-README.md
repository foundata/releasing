# `git-review-unpushed.sh`

`git-review-unpushed.sh` reviews commit messages that exist on the current local branch but not on its upstream branch. It fetches the relevant remote first, then visits the commits from oldest to newest.

For each commit, the helper can:

- Edit the message using the configured Git editor.
- Show the commit's diff against its parent using the configured Git pager.
- Continue to the next commit.
- Abort and restore the original branch.

Changing a message rewrites that commit and every following commit. The helper therefore refuses to run with a dirty working tree, during another Git history operation, on a divergent branch, or when the unpushed range contains merges.



## Usage

```sh
./git-review-unpushed.sh
./git-review-unpushed.sh -t /path/to/repository
./git-review-unpushed.sh -t /path/to/repository -u origin/main
```

Options:

- `-t repository`: Local Git repository. The default is the current directory.
- `-u upstream`: Comparison ref. The default is the current branch's configured upstream, such as `origin/main`.
- `-h`: Print command help.

The interactive actions are:

- `e`: Open `git commit --amend`, then show the same commit again.
- `d`: Show `git diff HEAD^ HEAD --`, then show the same commit again.
- `n`: Accept the current message and continue.
- `a`: Abort the rebase and restore the original branch.

`y` and `yes` are also accepted as aliases for `e`. `q` and `quit` are accepted as aliases for `a`.



## Git subcommand

Git discovers executables named `git-NAME` in `PATH`. Create a symlink without the `.sh` suffix and ensure `${HOME}/.local/bin` is in `PATH`:

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
