# The forge's release entry

```sh
release forge release-create "${version}" \
  --manifest "../dist-${version}/artifacts.json"
```

The notes are the changelog section for that version. The assets are the
manifest and the files it names. The write is performed by the forge's own
command-line tool, `gh` for GitHub.

The write explicitly names the declared forge host and repository, the same
destination checked during planning. Git remotes, `GH_REPO` and `GH_HOST`
cannot redirect it to another repository.

It refuses when the changelog has no section for the version, when the
manifest records a different version, when its files are missing or altered,
when the forge already has a release for the tag, and when no release tool is
known for the declared forge. Compatible manifests without a version field
remain accepted; the command's version selects the changelog section and tag.

The release tag must already exist on the forge. The write passes
`--verify-tag` to `gh`, so forgetting to push the tag fails instead of creating
a new tag at the default branch. Run `release push` before creating the entry.

`--dry-run` prints the command it would run and creates nothing. `--offline`
skips the question of whether a release already exists, for a forge that
cannot be reached.

## Table of contents<a id="toc"></a>

- [Credentials](#credentials)
- [How the forge is asked](#how-the-forge-is-asked)
- [Collections](#collections)

## Credentials<a id="credentials"></a>

The forge's own command-line tool performs the write, so it must be installed
and authenticated: `gh auth status` for GitHub. No credential is passed to it,
and none is read here.

## How the forge is asked<a id="how-the-forge-is-asked"></a>

The questions the release steps put to the forge are reads: does a release
exist for this tag, and which tag is the latest release. `tag create`, `tag
check`, `tag delete`, `forge release-create`, `status` and `verify` ask them.
A forge meters anonymous requests per address, GitHub at 60 per hour, and an
office shares one address, so each question is asked the first way that can
answer:

1. With a token from the environment, `GH_TOKEN` or `GITHUB_TOKEN` for GitHub.
   This is what a CI job provides, and the token stays in the process it was
   given to.
2. Through the forge's own tool and the login it holds, `gh api` for GitHub.
   The tool's credential never enters this package. A tool that is not
   installed or not logged in is skipped; one that is logged in and fails has
   answered, and the failure is reported as the forge's.
3. Anonymously.

The narration names the way that answered, `GET via gh` for the second. When
the anonymous allowance is used up, the error says when it resets and how to
ask as a user instead. `--offline` on the tag commands and `forge
release-create` asks nothing at all.

## Collections<a id="collections"></a>

A collection's notes come from `changelogs/changelog.yaml`, rendered as
Markdown with the section titles set in `changelogs/config.yaml`.
`release changelog show` prints the same text.

reStructuredText inline literals become Markdown code spans. Other markup is
passed through unchanged.
