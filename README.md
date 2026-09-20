# releasing

Release helpers for projects that publish from a Git-tracked source tree.

> **Important:** This tooling is built for foundata's release process(es). You
> are welcome to use it but Pull Requests to adapt our toolset to different
> release policies or processes are out of scope.

Components and tools:

- `release`: command that covers the error-prone steps around a release:
  preparing repository Markdown for package indexes, and, as the package grows,
  version sites, changelogs, artifacts, tags and post-publish verification. Each
  step is one subcommand; the order of steps stays in each project's own
  procedure.

<!-- rumdl-disable MD033 -->
<!-- HTML for consistent rendering across limited platform parsers -->
<div align="center" id="project-readme-header">
<br>
<br>

**⭐ Found this useful? Support open-source and star this project:**

[![GitHub repository](https://img.shields.io/github/stars/foundata/releasing.svg)](https://github.com/foundata/releasing)

<br>
</div>
<!-- rumdl-enable MD033 -->


## Installation

Add it to a development dependency group of the project that releases:

```toml
[dependency-groups]
dev = ["releasing"]
```

Run it without installing anything into the project:

```sh
uvx --from git+https://github.com/foundata/releasing release --help
```

Python 3.11 to 3.14 are supported. The minimum is 3.11 rather than the 3.12
baseline of the foundata Python guide because the package is a development
dependency of projects that target Debian 12, which ships Python 3.11.


## Commands

Project-aware commands read the release declaration, one table in
`pyproject.toml` or `releasing.toml`. Markdown preparation and explicit-version
artifact operations also work independently; see
[The release declaration](./docs/config.md).

- `release config check`: validate the declaration and every file it names,
  and print the effective values.
- `release version check` and `release version bump`: every declared
  version site, the lockfile, lockstep pins and the tag agree, or move them all
  to a new version. See [Version sites](./docs/version.md).
- `release changelog check`, `show` and `release`: Keep a Changelog
  sections, dates and links are consistent, one section is printed for a
  release description, or the unreleased entries become a dated section. See
  [Changelog sections](./docs/changelog.md).
- `release build`: export a committed revision, prepare the index Markdown
  inside that export, build, check and record a manifest. See
  [Building from an exported revision](./docs/build.md).
- `release tag create`, `check` and `delete`: a guarded annotated tag, and a
  deletion that stays legal only while no release exists. See
  [Release tags](./docs/tag.md).
- `release status`: report which steps of a release are done, pending or
  broken. See [Where a release stands](./docs/status.md).
- `release push`: publish the release branch and its tag together, after
  re-checking both. See [Publishing the branch and the tag](./docs/push.md).
- `release publish`: upload exactly the files a manifest names, refusing any
  other file beside them. See [Uploading what was validated](./docs/publish.md).
- `release forge release-create`: create the forge's release entry from the
  changelog and the manifest. See
  [The forge's release entry](./docs/forge-release.md).
- `release verify`: the index serves the validated files, an isolated install
  reports the version and the forge reports the tag as latest. See
  [Verifying a published release](./docs/verify.md).
- `release artifacts check`, `manifest` and `verify`: distributions carry
  the right version, a description without relative links and no litter; their
  digests are recorded and later compared. See [Artifacts](./docs/artifacts.md).
- `release markdown prepare`: rewrite repository-relative link and image
  destinations to absolute URLs without reformatting the document. See
  [Preparing Markdown for package indexes](./docs/markdown.md).

The end-to-end order for a Python project is in
[Releasing a Python package](./docs/python-packages.md).

Every command exits with `0` on success, `1` when a check or operation fails
and `2` on invalid usage. Diagnostics go to stderr; stdout carries only
generated output.


## Releasing this package

`releasing` releases itself with its own commands; see
[Releasing a Python package](./docs/python-packages.md). The declaration is
the `[tool.releasing]` table in `pyproject.toml`.

## Development

See the [development guide](./DEVELOPMENT.md) for the checks, the test layout
and the corpus maintenance.


## Licensing, copyright<a id="licensing-copyright"></a>

<!--REUSE-IgnoreStart-->
Copyright (c) 2026 foundata GmbH (<https://foundata.com>)

This project is licensed under the GNU General Public License v3.0 or later
(SPDX-License-Identifier: `GPL-3.0-or-later`), see
[`LICENSES/GPL-3.0-or-later.txt`](./LICENSES/GPL-3.0-or-later.txt) for the full
text.

The [`REUSE.toml`](./REUSE.toml) file provides detailed licensing and copyright
information in a human- and machine-readable format. This includes parts that
may be subject to different licensing or usage terms, such as third-party
components. The repository conforms to the
[REUSE specification](https://reuse.software/spec/). You can use
[`reuse spdx`](https://reuse.readthedocs.io/en/latest/readme.html#cli) to
create a
[SPDX software bill of materials (SBOM)](https://en.wikipedia.org/wiki/Software_Package_Data_Exchange).
<!--REUSE-IgnoreEnd-->

[![REUSE status](https://api.reuse.software/badge/github.com/foundata/releasing)](https://api.reuse.software/info/github.com/foundata/releasing)


## Author information<a id="author-information"></a>

This project was created and is maintained by
[foundata](https://foundata.com/).
