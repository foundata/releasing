# Verifying a published release

`release verify` runs three checks after an upload and stops at the first one
that fails.

```sh
release verify "../dist-${version}/artifacts.json"
```

First, the index has to serve the validated files. Every manifest file for the
selected distribution must be published with the same SHA-256, and the index
must serve no other file for that distribution and version. This compares the
bytes that were built and checked against
the bytes the index hands to users, which a version number alone cannot do.
PyPI reports a digest per file; Ansible Galaxy reports one for the collection
artifact.

Second, an isolated install has to report the version. `uv run --isolated
--no-project --refresh-package NAME --with NAME==VERSION` installs the
published distribution into a throwaway environment and reads its installed
metadata. The index listing is refreshed rather than taken from the local
cache, because this check runs moments after an upload, when a cached listing
still predates the version and the resolver would report it as nonexistent.
`--no-install` skips the step, for example on a machine without access to the
index.

Third, the forge has to report the version's tag as its latest release. That
catches a release someone forgot to create, or left as a draft.

`--distribution` selects which name to query and which manifest entries to
compare when a manifest holds several distributions, such as a workspace
releasing two packages. Run the command once per distribution to verify the
whole workspace. A single distribution is inferred from the artifact names;
Python names match regardless of case or hyphen, underscore and dot spelling.
The manifest needs no additional fields and the local artifacts are not needed.
`--version` supplies the version for a compatible manifest without one, or
asserts which version the manifest records, so a stale manifest cannot be
verified by accident.

The command only reads. It creates no release and uploads nothing. A
`GITHUB_TOKEN` in the environment is used only when the repository is private.
