# Publishing the branch and the tag

```sh
release push "${version}"
```

Pushes the branch, then the tag, after checking both.

It refuses when:

- `HEAD` is detached, so there is no branch to publish;
- the tag does not exist, is lightweight, or its message departs from the
  project's convention;
- the branch does not contain the tag's commit, which is the case a pair of
  `git push` lines cannot detect;
- the revision the tag names does not state the version, or its changelog does
  not document it. That check exports the revision, so it describes what was
  committed rather than what the working tree currently holds.

`--dry-run` asks the remote what would happen and sends nothing.

The remote is the one the current branch tracks, and `origin` when the branch
tracks nothing. `--remote NAME` names another one. The tag check before the
push compares against the same remote, so a fork releasing to `upstream` is
checked against `upstream`.

If the branch push fails, the tag is not sent.
