# Changelog sections

The `changelog` commands work on a
[Keep a Changelog](https://keepachangelog.com/) file in the layout the foundata
projects use: a `## [Unreleased]` section first, then `## [X.Y.Z] - YYYY-MM-DD`
sections newest first, and at the end one link definition per version plus
`[unreleased]` comparing the latest tag with `HEAD`:

```markdown
## [Unreleased]

- Nothing worth mentioning right now.


## [1.2.0] - 2026-08-27

### Added

- A feature.


[unreleased]: https://github.com/foundata/example/compare/v1.2.0...HEAD
[1.2.0]: https://github.com/foundata/example/releases/tag/v1.2.0
```

Edits are line based; nothing else in the file is reformatted, and headings
inside fenced code blocks are ignored. The link URLs come from the declared
forge and repository. For `changelog = "antsibull"`, antsibull-changelog owns
the file: `release` runs `antsibull-changelog release`, and `check --version`
confirms the version is recorded in `changelogs/changelog.yaml`.

## `release changelog check [--version X.Y.Z]`

Reports every structural problem: a first section that is not `Unreleased`, a
heading without a valid date, a label that is not a version, duplicate or
misordered sections, a version without a link definition, and an
`[unreleased]` link that does not compare the latest tag with `HEAD`. With
`--version`, the latest released section must be that version. `release
version check` runs the same check for the version it found.

## `release changelog show X.Y.Z`

Prints the section body to stdout, without the heading, for example as the
description of a forge release:

```sh
gh release create "v${version}" --title "v${version}" \
  --notes-file <(release changelog show "${version}")
```

`Unreleased` is accepted as the version.

## `release changelog release X.Y.Z [--date YYYY-MM-DD]`

Turns the entries under `Unreleased` into the section for the version, dated
today unless `--date` is given, puts a fresh `Unreleased` section with a
placeholder entry above it, points `[unreleased]` at the new tag and inserts
the version's tag link. It refuses to run when there are no entries, when the
section already exists, when the version is not newer than the latest one, or
when the file fails the structural check. `--placeholder` sets the entry of
the fresh `Unreleased` section.
