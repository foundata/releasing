# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).


## [Unreleased]

### Removed

- `load_manifest()` no longer accepts a digest written as `sha256:<hex>`, only
  the bare hexadecimal spelling that package indexes serve. Versions 1.0.1 and
  1.0.2 accepted both. The tolerance existed for one producer, ConClear's
  release gate, which now writes the shared format through `build_manifest()`
  and `dump_manifest()`.

  Retained release evidence written by that gate before the change, under
  `~/.local/share/conclear/distributions/<revision>/artifacts.json` for
  ConClear 1.0.0 and 1.0.1, carries prefixed digests and no longer passes
  `release artifacts verify`. The recorded files and digests remain valid;
  only this reader refuses them.


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


[unreleased]: https://github.com/foundata/releasing/compare/v1.0.2...HEAD
[1.0.2]: https://github.com/foundata/releasing/releases/tag/v1.0.2
[1.0.1]: https://github.com/foundata/releasing/releases/tag/v1.0.1
[1.0.0]: https://github.com/foundata/releasing/releases/tag/v1.0.0
