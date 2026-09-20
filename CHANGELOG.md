# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).


## [Unreleased]

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


[unreleased]: https://github.com/foundata/releasing/compare/v2.0.0...HEAD
[2.0.0]: https://github.com/foundata/releasing/releases/tag/v2.0.0
[1.0.2]: https://github.com/foundata/releasing/releases/tag/v1.0.2
[1.0.1]: https://github.com/foundata/releasing/releases/tag/v1.0.1
[1.0.0]: https://github.com/foundata/releasing/releases/tag/v1.0.0
