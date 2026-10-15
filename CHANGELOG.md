# Changelog

<!--
SPDX-FileCopyrightText: foundata GmbH <https://foundata.com>
SPDX-License-Identifier: GPL-3.0-or-later
-->

Notable, user-facing changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).


## [Unreleased]

- Nothing worth mentioning right now.


## [7.0.0] - 2026-10-15

### Changed

- Ansible collection builds now require a committed, script-runnable Nox setup
  and passing `ansible-test-sanity` sessions on the exact release commit. The
  gate uses an isolated clone, retains export-ignored tests, rejects skipped
  or missing sessions and tracked-file rewrites, and keeps diagnostics on
  failure. Dry runs show the command without running it.
- Galaxy publication now requires `ansibleSanity` evidence matching the
  manifest's source revision and artifact digests. Older manifests must be
  rebuilt with `release build`; `artifacts manifest` cannot supply this
  evidence. The Python build and PyPI publication paths are unchanged.

### Fixed

- Timed-out sanity commands stop their child processes before temporary build
  files are removed, preventing locked-directory errors on Windows. Partial
  command output remains available in the failure log.


## [6.0.0] - 2026-10-12

### Added

- `release markdown prepare --strip-html` prepares a document for a target that
  shows raw HTML as text, such as Quay's newer repository page: it removes
  comments and empty heading anchors, turns `<br>` into a Markdown line break or
  a space, and refuses any other raw HTML with its location. The library
  function takes `strip_html=True`.
- `release markdown prepare --absolute-anchors` points in-page `#anchor` links
  at the same anchor in the document on the forge, for a target without the
  document's anchors. The library function takes `absolute_anchors=True`.
- `release quay description-set` publishes the README of a Git ref as the
  description of one or more Quay repositories. The document is read from the
  ref, its relative links are checked against an export of it, and it is
  prepared with the header collapsed, HTML stripped and absolute anchors. The
  write uses a Quay API token from a file only its owner can read, skips a
  description that is already current and reads the stored description back.
  `--dry-run` shows the difference without writing.
- Failed uploads report tool-confirmed files, uncertain remote outcomes and
  files not attempted. Galaxy failures retain earlier successes; failed PyPI
  batches remain unconfirmed. No failed upload is automatically retried.
- Forge requests are made as a user when they can be. Every question to the
  forge, whether a release exists and which is latest, is asked first with a
  `GH_TOKEN` or `GITHUB_TOKEN` from the environment, then through the
  logged-in `gh`, and only then anonymously. GitHub allows an address 60
  anonymous requests per hour, and an office shares one address. The narration
  names the way that answered, and a used-up anonymous allowance now says when
  it resets and how to ask as a user. The `Forge` definition carries the tool
  and the token variables, so another forge adds one entry.

### Changed

- Forge release notes are read from the local release tag's commit, including
  collection changelog data and titles, rather than from the working tree.
- `release status` retries a missing forge release three times at five-second
  intervals when every other step is `ok`; `--no-wait` checks once.

### Fixed

- Atomic file writes apply permissions through the closed temporary file's
  path, so Markdown and changelog writes also work on Windows without `fchmod`.
- Index and forge uploads use private copies checked against the planned
  digests, including the forge's manifest attachment. Changed inputs are
  refused before any upload; staging is removed after success or failure.
- Forge creation checks a manifest's supplied repository and source revision
  against the declared project and the release tag's commit.
- Artifact manifests reject duplicate filenames and paths instead of basenames.
  Verification refuses symbolic links outside the artifact directory before
  reading their contents, so publication cannot attach those external files.
- Release commands report unreadable attribution-check revisions as CLI errors
  instead of tracebacks, including a missing local tag during forge creation.
- `release build` refuses README sources and copy destinations that resolve
  outside the export, preventing symbolic links from rewriting external files
  during a build or dry run.
- `forge release-create` explicitly targets the declared host and repository,
  preventing Git remotes or the forge tool's environment from redirecting the
  write to a different destination than the one checked.
- `forge release-create` requires the tag to exist on the forge, preventing
  `gh` from creating an unpushed release tag at the default branch.
- `forge release-create` rejects a manifest that records a different version
  from the requested release, even when all its file digests match.
- `forge release-create` stages notes in its own temporary directory, preserving
  existing checkout files and supporting tag names containing slashes. Staged
  notes are removed after success or failure; dry runs create no staging files.
- `forge release-create --project` keeps relative manifest and artifact paths
  anchored to the caller's directory when running the forge tool in the project.
- Artifact checks compare the filename's version field instead of searching
  for the expected version anywhere in the name. Python filenames use
  `packaging`, now a runtime dependency; collection prerelease suffixes and
  wheel build tags remain supported.


## [5.0.0] - 2026-09-26

### Added

- `source-repository`, the ecosystem for a repository that publishes no
  artifact and is released as its tag. It has no version site by default:
  `version check` reports the changelog's newest released section and compares
  `--expect` with it, `tag create` and `push` check that section, `verify`
  takes no manifest and checks that the remote holds the release tag and the
  forge reports it as latest, and `build`, `publish` and `version bump` refuse
  and name the step to take instead. See
  [Releasing a source repository](https://github.com/foundata/releasing/blob/main/docs/source-repositories.md).
- `release verify --remote` names the remote that must hold the release tag.
- A standalone declaration may be named `.releasing.toml` as well as
  `releasing.toml`, for repositories that keep their configuration in dotfiles.
  Both names are read and mean the same thing, and a declaration that appears
  in more than one file is refused with each of them named.

### Changed

- `changelog check`, and every command that runs it, refuses a release date in
  the future. A section dated tomorrow is a typo today.
- `version bump` refuses a project without version sites instead of rewriting
  nothing, running `uv lock` and reporting success.
- `releasing.config.STANDALONE` is now `releasing.config.STANDALONES`, the
  accepted standalone file names in search order.

### Removed

- The `hugo-component` ecosystem. A Hugo component is a repository released as
  its tag; declare `ecosystem = "source-repository"` instead, which applies the
  same defaults.


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


[unreleased]: https://github.com/foundata/releasing/compare/v7.0.0...HEAD
[7.0.0]: https://github.com/foundata/releasing/releases/tag/v7.0.0
[6.0.0]: https://github.com/foundata/releasing/releases/tag/v6.0.0
[5.0.0]: https://github.com/foundata/releasing/releases/tag/v5.0.0
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
