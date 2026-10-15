# Building from an exported revision

<!--
SPDX-FileCopyrightText: foundata GmbH <https://foundata.com>
SPDX-License-Identifier: GPL-3.0-or-later
-->

`release build` exports the committed revision with `git archive`, prepares the
package-index Markdown inside that export, builds there, checks the result and
records a manifest. The working tree stays untouched, so nothing has to be
restored afterwards and an uncommitted file cannot reach an artifact.

```sh
release build --out "../dist-${version}"
```

## Table of contents<a id="toc"></a>

- [What it does](#what-it-does)
- [Ansible sanity](#ansible-sanity)
- [Local dependency sources](#local-dependency-sources)
- [Output](#output)
- [Verifying and publishing what was built](#verifying-and-publishing)

## What it does<a id="what-it-does"></a>

1. Resolves `--revision` (default `HEAD`) to a full commit and exports it.
   `export-ignore` in `.gitattributes` keeps a tracked file out of the
   artifacts. The export ignores the machine's `core.autocrlf` and `core.eol`,
   which Git for Windows sets to convert line endings by default, so the same
   commit produces the same bytes everywhere; an `eol` attribute the
   repository declares still decides.
2. Loads the release declaration from the export and runs `version check`
   there, so the version that ships is the committed one. `--expect X.Y.Z`
   pins what that version has to be. A `source-repository` stops here: it is
   released as its tag and builds no artifact, and the command says so.
3. Runs the changelog check for that version. For an Ansible collection, also
   runs its sanity sessions on that exact commit before building.
4. Prepares every declared document: relative destinations are validated
   against the exported tree, rewritten against the forge at the version's tag
   ref, and copied over the documents named in `copies`. Document paths,
   including symbolic links in their parent directories, must resolve inside
   the export; this is checked during dry runs too.
5. Builds the distributions. For Python that is a source distribution from the
   export and a wheel from that source distribution, so what is published is
   what installing from source produces. For an Ansible collection it is
   `ansible-galaxy collection build`.
6. Runs the artifact checks and writes the files plus `artifacts.json` into
   `--out`, which must not exist yet. The directory appears complete or not at
   all.

## Ansible sanity<a id="ansible-sanity"></a>

Ansible collection builds require `uv` and a committed `noxfile.py` with the
`ansible-test-sanity` session provided by `antsibull-nox`. The script must
declare its dependencies using inline script metadata. Its selected concrete
`ansible-test-sanity-*` sessions determine the matrix and configured exceptions;
`release` adds no core versions. The existing container engine, Python
interpreters and network access those sessions need must be available.

The checks run in a temporary local clone of the selected commit, with all
tracked test files retained even when `export-ignore` excludes them from the
package. The clone is separate from the packaging export and the developer's
checkout. The command is:

```sh
CI=true ANTSIBULL_CHANGE_DETECTION=false uv run --quiet --no-project --script noxfile.py \
  -s ansible-test-sanity --error-on-missing-interpreters --report <report.json>
```

`release` discovers the selected sessions first and requires a successful Nox
report for every one. Empty selections, skips, missing interpreters, failed
commands, missing reports and changes to tracked files stop the build. Change
detection is disabled so release checks cover the whole collection. These are
the project's trusted sanity sessions; the report is not an independent audit
of their implementation or configured exceptions.

The sanity command has a two-hour timeout. Its combined output goes to the
diagnostic path printed before it starts. Failure leaves that directory and
its reports available for inspection; success removes it. Diagnostics can
contain private dependency locations or tool output, so review them before
sharing and remove them when no longer needed. No artifact output directory
is created for a failed gate.

The manifest records `ansibleSanity`: passing session names, the tested commit,
`releasing`, `uv` and Nox versions, and the built artifact digests. Galaxy
publication requires evidence matching the manifest's source and files. It is
a local release record, not a cryptographically signed attestation. Python
builds and PyPI publication are unchanged.

Installed-artifact acceptance against the real product remains a separate
collection-specific step after building and before publication.

## Local dependency sources<a id="local-dependency-sources"></a>

A `[tool.uv.sources]` entry with a `path` records a directory from the machine
that wrote it, in `pyproject.toml` and in the lockfile. Both can ship inside a
source distribution, so the build refuses a revision that has one:

```text
Error: this revision resolves dependencies from local directories, so its
artifacts would publish a path from this machine:
  pyproject.toml: releasing = /home/user/dev/releasing
```

`--allow-local-sources` builds anyway and prints a warning on every run, for a
throwaway build while a dependency is not published yet. Those artifacts must
never be uploaded. Workspace sources name no directory and are not affected.

## Output<a id="output"></a>

```text
../dist-1.0.0/
├── artifacts.json
├── sample-1.0.0-py3-none-any.whl
└── sample-1.0.0.tar.gz
```

The artifact paths go to stdout, one per line, so a publishing step can read
them, followed by the path of the manifest. Everything else, including the
commands that built them, goes to stderr.

`--dry-run` exports the revision and checks its metadata and README links, then
reports the sanity and build commands without running them. It writes no output
directory or passing sanity evidence and records no artifact digests.

Because the build runs before the tag exists, the prepared links point at the
version's tag ref (`refs/tags/vX.Y.Z` by default). The tag is pushed with the
release, or the artifacts are never uploaded.

## Verifying and publishing what was built<a id="verifying-and-publishing"></a>

`release publish` re-checks every digest against the bytes on disk and uploads
exactly the files the manifest names, so a file beside them that nothing
validated is a refusal rather than an extra upload:

```sh
release publish "../dist-${version}/artifacts.json"
```

`release artifacts verify` makes the same comparison without uploading, for a
check that stands on its own. See
[Uploading what was validated](./publish.md).
