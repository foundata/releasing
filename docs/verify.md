# Verifying a published release

An upload is not a release until the index serves what was validated and the
forge points at the version. `release verify` asks all three questions and
fails on the first that does not answer.

```sh
release verify "../dist-${version}/artifacts.json"
```

1. **The index serves the validated files.** Every file in the manifest must
   be published with the same SHA-256, and the index must serve no additional
   file for that version. This compares the bytes that were checked and built
   with the bytes the index hands to users, which a version number alone
   cannot do. PyPI reports a digest per file; Ansible Galaxy reports one for
   the collection artifact.
2. **An isolated install reports the version.** `uv run --isolated
   --no-project --with NAME==VERSION` installs the published distribution into
   a throwaway environment and asks its installed metadata. `--no-install`
   skips this, for instance on a machine without network access to the index.
3. **The forge reports the tag as latest.** The release API must name the
   version's tag, so a forgotten or draft release is caught.

`--distribution` selects which name to query when a manifest holds several
distributions, such as a workspace releasing two packages. `--version` asserts
which version the manifest records, so a stale manifest cannot be verified by
accident.

The command is read-only. It creates no release, uploads nothing and needs no
credentials; a `GITHUB_TOKEN` in the environment is used only when the
repository is private.
