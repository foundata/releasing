# Verifying a published release

<!--
SPDX-FileCopyrightText: foundata GmbH <https://foundata.com>
SPDX-License-Identifier: GPL-3.0-or-later
-->

`release verify` checks the published artifacts and the forge release, stopping
at the first failure. For PyPI, it also checks an isolated installation. A
project that uploads nothing verifies its tag instead of artifacts; see
[A release that is a tag](#a-release-that-is-a-tag).

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

For PyPI only, an isolated install then has to report the version.
`uv run --isolated --no-project --refresh-package NAME --with NAME==VERSION`
installs the published distribution into a throwaway environment and reads its
installed metadata. The index listing is refreshed rather than taken from the
local cache, because this check runs moments after an upload, when a cached
listing still predates the version and the resolver would report it as
nonexistent. `--no-install` skips this step; the index and forge checks still
require network access. Ansible Galaxy verification does not install the
collection.

Finally, the forge has to report the version's tag as its latest release. That
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

## A release that is a tag<a id="a-release-that-is-a-tag"></a>

A project with `index = "none"` publishes no artifact, so there is no index to
ask and the command takes no manifest. The tag is the release, and the checks
are what that leaves to verify: the release tag exists here as an annotated
tag with the project's message, the remote holds the identical tag object, and
the forge reports it as latest.

```sh
release verify --version "${version}"
```

Without `--version`, the newest released section of the changelog names the
release. The remote is the one the current branch tracks, and `origin` when
the branch tracks nothing; `--remote NAME` names another one.

The command only reads. It creates no release and uploads nothing. The forge
request uses a token from the environment, the logged-in `gh`, or goes
anonymous, in that order; see
[How the forge is asked](./forge-release.md#how-the-forge-is-asked).
