# Artifacts

The `artifacts` commands inspect built distributions without extracting them:
wheels, source distributions and Ansible collection tarballs. The checks cover
the defects these projects have shipped before: an index page whose relative
links were never rewritten, and a wheel carrying a tool cache directory.

## `release artifacts check FILE...`

Fails, naming every problem, when any file:

- carries another version in its metadata or its file name than expected;
- has a Markdown description (the index page) with repository-relative link
  or image destinations, found by the same Markdown parser `release markdown
  prepare` uses;
- contains a tool cache, `__pycache__`, bytecode, a `.git` directory, editor or
  patch leftovers;
- contains an absolute path, a `..` component or a symbolic link.

Source distributions and collection tarballs must have non-empty descriptions.
An empty wheel description is accepted; a whitespace-only description still
fails. Python descriptions declared as a non-Markdown content type are treated
as absent by these checks.

The expected version is `--version`, or otherwise the version the project's
sites state (`release version check`). With a project, every declared
distribution name must have an artifact. For collection tarballs the README
named in `MANIFEST.json` is the description.

## `release artifacts manifest FILE... --out artifacts.json`

Checks the supplied files, then records the SHA-256 and size of every file.
Unlike `artifacts check` with a project declaration, this command does not
require an artifact for every declared distribution:

```json
{
  "schemaVersion": 1,
  "generator": "releasing",
  "repository": "foundata/example",
  "version": "1.2.3",
  "sourceRevision": "…",
  "created": "2026-09-20T10:00:00+00:00",
  "artifacts": [
    { "filename": "example-1.2.3-py3-none-any.whl", "sha256": "…", "size": 12345 }
  ]
}
```

`--revision` records the commit the files were built from. `--dry-run`
shows the manifest it would record and writes no file. A gate that calls
`releasing.artifacts.dump_manifest()` directly can add producer-specific
top-level keys through its `extra` argument, for example the revision of a guide
the gate implements; they may not shadow the standard keys, and readers of the
standard shape ignore them. The manifest is never overwritten. `release build`
writes it as part of every build; other gates that produce a JSON file with the
same `artifacts` list can be verified with the same tools. Digests are bare
hexadecimal, the spelling package indexes serve; an algorithm prefix such as
`sha256:<hex>` is refused. A manifest without a `version` needs `--version`
when verifying.

## `release artifacts verify artifacts.json`

Fails when a listed file is missing or altered, or when an unlisted wheel or
tarball lies beside the manifest. Run it directly before uploading, so exactly
the validated bytes are published.
