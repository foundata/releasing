# The forge's release entry

```sh
release forge release-create "${version}" \
  --manifest "../dist-${version}/artifacts.json"
```

The notes are the changelog section for that version. The assets are the
manifest and the files it names. The write is performed by the forge's own
command-line tool, `gh` for GitHub.

It refuses when the changelog has no section for the version, when the
manifest's files are missing or altered, when the forge already has a release
for the tag, and when no release tool is known for the declared forge.

`--dry-run` prints the command it would run and creates nothing. `--offline`
skips the question of whether a release already exists, for a forge that
cannot be reached.

## Table of contents<a id="toc"></a>

- [Credentials](#credentials)
- [Collections](#collections)

## Credentials<a id="credentials"></a>

The forge's own command-line tool performs the write, so it must be installed
and authenticated: `gh auth status` for GitHub. No credential is passed to it,
and none is read here.

## Collections<a id="collections"></a>

A collection's notes come from `changelogs/changelog.yaml`, rendered as
Markdown with the section titles set in `changelogs/config.yaml`.
`release changelog show` prints the same text.

reStructuredText inline literals become Markdown code spans. Other markup is
passed through unchanged.
