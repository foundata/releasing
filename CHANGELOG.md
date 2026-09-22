# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).


## [Unreleased]

### Fixed

- Every request to a forge or an index asks for a revalidated answer. A release
  changes these answers and reads them back within seconds, where an anonymous
  request could be served the state from before the change: a release created
  moments earlier reported as still missing.


## [3.0.0] - 2026-09-22

### Changed

- `release` narrates its work on standard error: what is being checked, every
  command that changes something and every request to a forge or an index.
  `--quiet`, accepted before or after the command, prints the result only.
- Standard output carries the product of a command and nothing else. A check
  answers with its exit status, so `changelog check`, `tag check`,
  `artifacts verify`, `verify`, `push` and `publish` print nothing there, and
  the diff of `version bump` moved to standard error with the rest of the
  story. `status` prints its conclusion with its report instead of splitting
  them across two streams.
- `forge release-create` prints the URL of the release entry it created.
- A failing external program is named with its subcommand, for example
  `git archive failed with status 128`.

### Added

- `--dry-run` on every command that changes something: `version bump`,
  `changelog release`, `build`, `tag create`, `tag delete` and
  `artifacts manifest --out`, alongside the commands that already had it.


## [2.2.0] - 2026-09-20

### Added

- `release tag create X.Y.Z --manifest PATH` refuses to tag a revision the
  manifest's artifacts were not built from, which no other check can notice
  once the working tree is clean again.


## [2.1.0] - 2026-09-20

### Added

- `release status X.Y.Z` reports which steps of a release are done, pending or
  broken, and exits non-zero until every one is done.
- `release push X.Y.Z` publishes the release branch and its tag together,
  refusing a tag the branch does not contain.
- `release publish MANIFEST` uploads exactly the files a manifest names,
  refusing a stale or altered file beside them.
- `release forge release-create X.Y.Z` creates the forge's release entry from
  the changelog section and the manifest's files, through the forge's own
  command-line tool.
- `release changelog show` and the forge release entry render a collection's
  notes from `changelogs/changelog.yaml`, which antsibull-changelog owns.

### Fixed

- A command that contacts the configured remote is bounded and may not ask for
  credentials. An unreachable remote failed after the full local timeout, ten
  minutes, instead of promptly.


## [2.0.0] - 2026-09-20

### Removed

- `load_manifest()` accepts only bare hexadecimal digests. A manifest whose
  digests are written as `sha256:<hex>` no longer verifies.


## [1.0.2] - 2026-09-20

### Added

- `releasing.artifacts.dump_manifest()` accepts `extra` top-level keys, so a
  gate can record producer-specific facts such as the revision of a guide it
  implements without keeping a manifest format of its own.

### Fixed

- `release verify` installs the version it is verifying instead of failing
  with "no solution found". The isolated install resolved from the local
  index cache, which still predates a version published moments earlier, so
  verifying a fresh release reported it as nonexistent.


## [1.0.1] - 2026-09-20

### Fixed

- `release verify` reads a manifest whose digests are written as
  `sha256:<hex>`. Only the bare hexadecimal spelling was accepted, so a
  manifest from another gate was rejected as malformed.


## [1.0.0] - 2026-09-20

- All functionality and files.


[unreleased]: https://github.com/foundata/releasing/compare/v3.0.0...HEAD
[3.0.0]: https://github.com/foundata/releasing/releases/tag/v3.0.0
[2.2.0]: https://github.com/foundata/releasing/releases/tag/v2.2.0
[2.1.0]: https://github.com/foundata/releasing/releases/tag/v2.1.0
[2.0.0]: https://github.com/foundata/releasing/releases/tag/v2.0.0
[1.0.2]: https://github.com/foundata/releasing/releases/tag/v1.0.2
[1.0.1]: https://github.com/foundata/releasing/releases/tag/v1.0.1
[1.0.0]: https://github.com/foundata/releasing/releases/tag/v1.0.0
