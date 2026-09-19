# Release tags

A release tag is annotated, carries the project's message convention and points
at the revision whose artifacts were built. The `tag` commands enforce that and
protect the one escape the release procedures document.

## `release tag create X.Y.Z`

Creates the annotated tag (`vX.Y.Z` with the message `version X.Y.Z` by
default; both come from the declaration). It refuses when:

- the working tree is not clean, including untracked files, because a tag names
  a committed state;
- a version site, the lockfile, a lockstep pin or the changelog disagrees with
  the version;
- the tag already exists locally or on the remote.

`--revision` tags something other than `HEAD`. Pushing stays a separate,
explicit step.

## `release tag check X.Y.Z`

Reports why an existing tag is not a valid release tag: it is lightweight
rather than annotated, its message is not the convention, it points elsewhere
than the revision, or the remote's tag differs from the local one.

## `release tag delete X.Y.Z`

Deletes the tag locally and on the remote, but only while no forge release
exists for it. That condition is what makes the documented "delete the tag and
start over" escape legal: once a release exists the version is spent, the
artifacts may already have been downloaded, and the fix needs a new version.

```sh
release tag delete "${version}"     # refused once a release exists
```

`--local` keeps the remote tag. `--offline` skips the forge query, for a
repository whose forge is unreachable; it also means the release condition is
not checked, so use it only when you know no release exists.
