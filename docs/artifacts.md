# Artifacts

The `artifacts` commands inspect built distributions without extracting them:
wheels, source distributions and Ansible collection tarballs. Their checks are
the ones that caught real defects in published releases.

## `release artifacts check FILE...`

Fails, naming every problem, when any file:

- carries another version in its metadata or its file name than expected;
- has a description (the index page) with repository-relative link or image
  destinations, found by the same Markdown parser `release markdown prepare`
  uses, or no description at all;
- contains a tool cache, `__pycache__`, bytecode, a `.git` directory, editor or
  patch leftovers;
- contains an absolute path, a `..` component or a symbolic link.

The expected version is `--version`, or otherwise the version the project's
sites state (`release version check`). With a project, every declared
distribution name must have an artifact. For collection tarballs the README
named in `MANIFEST.json` is the description.

## `release artifacts manifest FILE... --out artifacts.json`

Runs the same checks, then records the SHA-256 and size of every file:

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

`--revision` records the commit the files were built from. The manifest is
never overwritten. `release build` writes it as part of every build; other
gates that produce a JSON file with the same `artifacts` list can be verified
with the same tools.

## `release artifacts verify artifacts.json`

Fails when a listed file is missing or altered, or when an unlisted wheel or
tarball lies beside the manifest. Run it directly before uploading, so exactly
the validated bytes are published.
