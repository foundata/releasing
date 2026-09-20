# Uploading what was validated

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

The declaration's `index` decides which tool does the upload: `uv publish` for
PyPI, `ansible-galaxy collection publish` for Ansible Galaxy, one file at a
time. An ecosystem that publishes nothing is refused rather than silently
skipped.

`--dry-run` lists what would be sent and uploads nothing.

## Credentials

The index's own tool reads them: from `UV_PUBLISH_TOKEN`, from
`ANSIBLE_GALAXY_SERVER_TOKEN`, from trusted publishing, or from its own
configuration. This command accepts no credential as an argument.

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
