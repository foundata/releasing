# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).


## [Unreleased]

### Added

- A standalone declaration may be named `.releasing.toml` as well as
  `releasing.toml`, for repositories that keep their configuration in dotfiles.
  Both names are read and mean the same thing, and a declaration that appears
  in more than one file is refused with each of them named.

### Changed

- `changelog check`, and every command that runs it, refuses a release date in
  the future. A section dated tomorrow is a typo today.
- `releasing.config.STANDALONE` is now `releasing.config.STANDALONES`, the
  accepted standalone file names in search order.


## [4.2.0] - 2026-09-24

### Fixed

- `publish` looks for a Galaxy credential where `ansible-galaxy` reads one.
  There is no `ANSIBLE_GALAXY_SERVER_TOKEN`: ansible-core builds the variable
  name from the server's own name and reads it only for a server
  `ANSIBLE_GALAXY_SERVER_LIST` names. The documented variable therefore did
  nothing, and the check that watched it stayed silent when no credential was
  present and warned when one was. The warning now names the three variables
  that belong together, accepts a token file, and is printed during a
  `--dry-run` too.

### Changed

- `reporting.program()`, `reporting.render()` and `reporting.wants_colour()`
  take the platform whose rules to follow, instead of reading the one they run
  on. The behaviour is unchanged; both sets of rules can now be asserted from
  either platform.


## [4.1.0] - 2026-09-23

### Added

- [Releasing an Ansible collection](https://github.com/foundata/releasing/blob/main/docs/ansible-collections.md),
  the recipe for the ecosystem: the declaration, what `build_ignore` has to
  exclude, the antsibull-changelog steps and the Galaxy upload.

### Fixed

- The product and the story are the same bytes on every platform and in every
  locale: UTF-8, with LF line endings. A Windows console encodes in its
  codepage, where the narration marker is one byte or not encodable at all, and
  a command could stop mid-sentence over a character the codepage lacks.
- An echoed command and a failure name the program as `git`, not as `git.EXE`.
- `changelog check` on a collection said it had checked `antsibull` instead of
  naming `changelogs/changelog.yaml`. Every command now names the file the
  changelog is kept in, whichever format owns it.
- The export a build and a tag check run on no longer depends on the machine's
  line-ending configuration. `git archive` applies `core.autocrlf` and
  `core.eol`, which Git for Windows sets to convert by default, so the same
  commit produced different artifacts there: a source distribution of 65301
  bytes against 64694 for the Linux build of the same revision. An `eol`
  attribute the repository declares still decides.

### Changed

- The attribution check reads only the commits the release remote does not
  have yet. A published message can no longer be amended for free, so refusing
  a release over one blocked work that the refusal could not fix; a repository
  with such a commit in its history releases again.


## [4.0.0] - 2026-09-23

### Changed

- A repository whose commit messages credit a tool as their author no longer
  releases: `tag create`, `push` and `forge release-create` refuse it until the
  message is amended, `allowed-attribution` names what the project carries on
  purpose, or `--allow-tool-attribution` permits it once.
- Every narrated line begins with a verb from a closed vocabulary: a participle
  while the work runs, a past tense once it is done, `Would` for what a dry run
  declined. The wording of many lines changed with it.

### Added

- `--remote` on `tag create`, `tag check`, `tag delete`, `status` and `push`
  names the remote to ask about the tag. Without it, commands use the remote
  the current branch tracks, and `origin` when it tracks none.
- `config check` reports the declared dependency pins and allowed attributions
  along with the rest of the effective declaration.
- `tag create`, `push` and `forge release-create` refuse a commit that credits
  a tool as its author; `--allow-tool-attribution` permits it once, and
  `allowed-attribution` in the declaration permits a named rule, or the values
  a regular expression finds, for a project that carries one on purpose.
- The narration is coloured on a terminal: the verb that opens a line, the
  answer to a request, and the `Error:` and `WARNING:` prefixes. Redirected
  output stays plain, so a captured story remains a clean record. `NO_COLOR`
  suppresses the styling and `FORCE_COLOR` demands it where no terminal is
  detected.

### Fixed

- Commands that ask a remote about the release tag asked `origin`, whatever the
  release is pushed to. A fork releasing to another remote was told its tag was
  absent, was compared against a leftover tag on `origin`, and had `tag delete`
  report success while the tag stayed on the remote it was released to. Where a
  message named "the remote", it now names the remote it asked.
- `tag delete --local` no longer reports a deletion it did not perform when the
  tag exists only on the remote.
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


[unreleased]: https://github.com/foundata/releasing/compare/v4.2.0...HEAD
[4.2.0]: https://github.com/foundata/releasing/releases/tag/v4.2.0
[4.1.0]: https://github.com/foundata/releasing/releases/tag/v4.1.0
[4.0.0]: https://github.com/foundata/releasing/releases/tag/v4.0.0
[3.0.0]: https://github.com/foundata/releasing/releases/tag/v3.0.0
[2.2.0]: https://github.com/foundata/releasing/releases/tag/v2.2.0
[2.1.0]: https://github.com/foundata/releasing/releases/tag/v2.1.0
[2.0.0]: https://github.com/foundata/releasing/releases/tag/v2.0.0
[1.0.2]: https://github.com/foundata/releasing/releases/tag/v1.0.2
[1.0.1]: https://github.com/foundata/releasing/releases/tag/v1.0.1
[1.0.0]: https://github.com/foundata/releasing/releases/tag/v1.0.0
