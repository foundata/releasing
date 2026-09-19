# Verifying a published release

`release verify` runs three checks after an upload and stops at the first one
that fails.

```sh
release verify "../dist-${version}/artifacts.json"
```

First, the index has to serve the validated files. Every file in the manifest
must be published with the same SHA-256, and the index must serve no other file
for that version. This compares the bytes that were built and checked against
the bytes the index hands to users, which a version number alone cannot do.
PyPI reports a digest per file; Ansible Galaxy reports one for the collection
artifact.

Second, an isolated install has to report the version. `uv run --isolated
--no-project --with NAME==VERSION` installs the published distribution into a
throwaway environment and reads its installed metadata. `--no-install` skips
this, for example on a machine without access to the index.

Third, the forge has to report the version's tag as its latest release. That
catches a release someone forgot to create, or left as a draft.

`--distribution` selects which name to query when a manifest holds several
distributions, such as a workspace releasing two packages. `--version` asserts
which version the manifest records, so a stale manifest cannot be verified by
accident.

The command only reads. It creates no release and uploads nothing. A
`GITHUB_TOKEN` in the environment is used only when the repository is private.
