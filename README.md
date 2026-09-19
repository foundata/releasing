# releasing

Release helpers for projects that publish from a Git-tracked source tree. The
`release` command covers the error-prone steps around a release: preparing
repository Markdown for package indexes, and, as the package grows, version
sites, changelogs, artifacts, tags and post-publish verification. Each step is
one subcommand; the order of steps stays in each project's own procedure.

The package is under development towards its first release, `1.0.0`, and is
not on PyPI yet.


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

Every command reads the project's release declaration, one table in
`pyproject.toml` or `releasing.toml`; see
[The release declaration](./docs/config.md).

- `release config check`: validate the declaration and every file it names,
  and print the effective values.
- `release version check` and `release version bump`: every declared
  version site, the lockfile, lockstep pins and the tag agree, or move them all
  to a new version. See [Version sites](./docs/version.md).
- `release markdown prepare`: rewrite repository-relative link and image
  destinations to absolute URLs without reformatting the document. See
  [Preparing Markdown for package indexes](./docs/markdown.md).

Every command exits with `0` on success, `1` when a check or operation fails
and `2` on invalid usage. Diagnostics go to stderr; stdout carries only
generated output.


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


## Author information<a id="author-information"></a>

This project was created and is maintained by
[foundata](https://foundata.com/).
