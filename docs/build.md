# Building from an exported revision

`release build` exports the committed revision with `git archive`, prepares the
package-index Markdown inside that export, builds there, checks the result and
records a manifest. The working tree stays untouched, so nothing has to be
restored afterwards and an uncommitted file cannot reach an artifact.

```sh
release build --out "../dist-${version}"
```

## What it does

1. Resolves `--revision` (default `HEAD`) to a full commit and exports it.
   `export-ignore` in `.gitattributes` keeps a tracked file out of the
   artifacts.
2. Loads the release declaration from the export and runs `version check`
   there, so the version that ships is the committed one. `--expect X.Y.Z`
   pins what that version has to be.
3. Runs the changelog check for that version.
4. Prepares every declared document: relative destinations are validated
   against the exported tree, rewritten against the forge at the version's tag
   ref, and copied over the documents named in `copies`.
5. Builds the distributions. For Python that is a source distribution from the
   export and a wheel from that source distribution, so what is published is
   what installing from source produces. For an Ansible collection it is
   `ansible-galaxy collection build`.
6. Runs the artifact checks and writes the files plus `artifacts.json` into
   `--out`, which must not exist yet. The directory appears complete or not at
   all.

## Local dependency sources

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

## Output

```text
../dist-1.0.0/
├── artifacts.json
├── sample-1.0.0-py3-none-any.whl
└── sample-1.0.0.tar.gz
```

The artifact paths go to stdout, one per line, so a publishing step can read
them, followed by the path of the manifest. Everything else, including the
commands that built them, goes to stderr.

`--dry-run` exports the revision and runs every check, then reports the build
commands it would run without running them. It writes no output directory and
records no digests, because there are no artifacts to hash.

Because the build runs before the tag exists, the prepared links point at the
version's tag ref (`refs/tags/vX.Y.Z` by default). The tag is pushed with the
release, or the artifacts are never uploaded.

## Verifying and publishing what was built

`release publish` re-checks every digest against the bytes on disk and uploads
exactly the files the manifest names, so a file beside them that nothing
validated is a refusal rather than an extra upload:

```sh
release publish "../dist-${version}/artifacts.json"
```

`release artifacts verify` makes the same comparison without uploading, for a
check that stands on its own. See
[Uploading what was validated](./publish.md).
