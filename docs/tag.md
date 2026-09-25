# Release tags

A release tag is annotated, carries the project's message convention and points
at the revision whose artifacts were built. The `tag` commands enforce that,
and they keep the escape hatch in the release procedures usable.

## Table of contents<a id="toc"></a>

- [`release tag create X.Y.Z`](#tag-create)
- [`release tag check X.Y.Z`](#tag-check)
- [`release tag delete X.Y.Z`](#tag-delete)
- [The remote these commands ask](#the-remote-these-commands-ask)

## `release tag create X.Y.Z`<a id="tag-create"></a>

Creates the annotated tag, by default `vX.Y.Z` with the message
`version X.Y.Z`; both come from the declaration. It refuses when:

- the working tree is not clean, including untracked files, because a tag names
  a committed state;
- a version site, the lockfile, a lockstep pin or the changelog disagrees with
  the version;
- the tag already exists locally or on the remote;
- with `--manifest`, the revision is not the one those artifacts were built
  from.

`--manifest` takes the manifest `release build` wrote and refuses a tag for a
revision nothing validated. A commit made between the build and the tag leaves
the working tree clean and every version site correct, so no other check
notices it. The manifest must also record the version being tagged, and one
without a source revision is refused rather than accepted.

```sh
release tag create "${version}" --manifest "${dist}/artifacts.json"
```

`--dry-run` runs every check and reports the tag it would create, without
creating it.

`--revision` tags something other than `HEAD`. The version and changelog
checks read that committed revision's declaration and files in a temporary
export, including its lockfile and dependency pins. The current declaration
supplies the tag name and message. The working tree is left untouched.
Pushing is a separate step.

## `release tag check X.Y.Z`<a id="tag-check"></a>

Reports why an existing tag cannot serve as the release tag: it is lightweight
instead of annotated, its message departs from the convention, it points
somewhere other than the revision, or the remote's tag differs from the local
one.

## `release tag delete X.Y.Z`<a id="tag-delete"></a>

Deletes the tag locally and on the remote, but only while no forge release
exists for it. That is what keeps the documented "delete the tag and start
over" escape usable: once a release exists, people may already have downloaded
the artifacts, so the fix needs a new version.

```sh
release tag delete "${version}"     # refused once a release exists
```

`--dry-run` reports which deletions would happen and performs none.

`--local` keeps the remote tag and asks no remote at all. `--offline` skips the
forge query for a repository whose forge is unreachable. It also skips the
release condition, so use it only when you know no release exists.

## The remote these commands ask<a id="the-remote-these-commands-ask"></a>

`create`, `check` and `delete` ask a remote whether it already has the tag, and
`delete` removes it there. That remote is the one the current branch tracks,
which is what a fork workflow needs, and `origin` when the branch tracks
nothing. `--remote NAME` names another one.
