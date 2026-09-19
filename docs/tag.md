# Release tags

A release tag is annotated, carries the project's message convention and points
at the revision whose artifacts were built. The `tag` commands enforce that,
and they keep the escape hatch in the release procedures usable.

## `release tag create X.Y.Z`

Creates the annotated tag, by default `vX.Y.Z` with the message
`version X.Y.Z`; both come from the declaration. It refuses when:

- the working tree is not clean, including untracked files, because a tag names
  a committed state;
- a version site, the lockfile, a lockstep pin or the changelog disagrees with
  the version;
- the tag already exists locally or on the remote.

`--revision` tags something other than `HEAD`. Pushing is a separate step.

## `release tag check X.Y.Z`

Reports why an existing tag cannot serve as the release tag: it is lightweight
instead of annotated, its message departs from the convention, it points
somewhere other than the revision, or the remote's tag differs from the local
one.

## `release tag delete X.Y.Z`

Deletes the tag locally and on the remote, but only while no forge release
exists for it. That is what keeps the documented "delete the tag and start
over" escape usable: once a release exists, people may already have downloaded
the artifacts, so the fix needs a new version.

```sh
release tag delete "${version}"     # refused once a release exists
```

`--local` keeps the remote tag. `--offline` skips the forge query for a
repository whose forge is unreachable. It also skips the release condition, so
use it only when you know no release exists.
