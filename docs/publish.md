# Uploading what was validated

<!--
SPDX-FileCopyrightText: foundata GmbH <https://foundata.com>
SPDX-License-Identifier: GPL-3.0-or-later
-->

```sh
release publish "../dist-${version}/artifacts.json"
```

Uploads the files the manifest names, after re-checking each digest against
the bytes on disk. A file beside them that the manifest does not name is a
refusal:

```text
Error: the files beside the manifest are not the validated set:
  releasing-1.0.2.tar.gz: not in the manifest
```

It also refuses a file the manifest names but the directory lacks, and one
whose content no longer matches its recorded digest.

Before invoking an upload tool, every input is copied into a private temporary
directory and the copy is checked against the planned digest. Changes between
planning and staging abort the upload; later changes to the originals cannot
change the copies being sent. All staged copies are removed after success,
failure or interruption. A dry run creates no staging files.

The declaration's `index` decides which tool does the upload: `uv publish` for
PyPI, `ansible-galaxy collection publish` for Ansible Galaxy, one file at a
time. An ecosystem that publishes nothing is refused rather than silently
skipped.

`--dry-run` lists what would be sent and uploads nothing.

Galaxy publication, including its dry run, requires passing `ansibleSanity`
evidence from [the build gate](./build.md#ansible-sanity). The tested revision
and artifact digests must match the manifest. Old manifests and those created
with `release artifacts manifest` have no such evidence: rebuild the release
with `release build` before publishing. There is no skip flag. PyPI publication
continues to accept the existing manifest format.

## Interrupted uploads

An upload failure reports three sets: files confirmed by successful tool calls,
files whose remote outcome is unconfirmed, and files not yet attempted. For
Galaxy, a later failure retains the successful earlier calls and stops before
the remaining files. A failed PyPI batch leaves every file in that batch
unconfirmed; a lost response does not prove the server rejected the upload.

The command does not retry or automatically skip files. Inspect the index before
retrying. An existing filename may be skipped only after its remote SHA-256
matches the original manifest; a mismatch requires investigation, not an
overwrite. Keep the original manifest as the release record. Library callers
can inspect `UploadError.completed`, `.uncertain` and `.pending`.

## Credentials

The index's own tool reads them: from the environment, from trusted publishing,
or from its own configuration. This command accepts no credential as an
argument, and warns before an upload when it can find none.

For PyPI that is `UV_PUBLISH_TOKEN`. For Ansible Galaxy there is no single
variable: `ansible-galaxy` builds the name from the server's own name and reads
it only for a server `ANSIBLE_GALAXY_SERVER_LIST` names, so all three belong
together.

```sh
export ANSIBLE_GALAXY_SERVER_LIST=galaxy
export ANSIBLE_GALAXY_SERVER_GALAXY_URL=https://galaxy.ansible.com/api/
export ANSIBLE_GALAXY_SERVER_GALAXY_TOKEN="${token}"
```

The name `galaxy` is a label of your choosing; it only has to match in all
three. A token file works too: `ANSIBLE_GALAXY_TOKEN_PATH` pointing at a file
that holds `token: ...`.

```sh
printf 'PyPI API token: '
read -rs UV_PUBLISH_TOKEN
printf '\n'
export UV_PUBLISH_TOKEN

release publish "../dist-${version}/artifacts.json"

unset UV_PUBLISH_TOKEN
```

A version can be uploaded only once. Run `release artifacts verify` or this
command's dry run first if you want to see the set before it leaves.
