# Releasing a source repository

The order below is the one the commands assume. Each step produces a result
the next one depends on, so a skipped step is a missing result rather than a
shortcut.

A source repository publishes no artifact. Consumers clone or check out the
repository at a tag, so the tag is the release: there is nothing to build,
nothing to upload and no index to verify against. The version has no file of
its own either; it lives in the newest released section of the changelog and
in the tag that names it. The declaration says so once and every command
follows.

## Table of contents<a id="toc"></a>

- [Declaring the release](#declaring-the-release)
- [What the release needs](#what-the-release-needs)
- [Before the release](#before-the-release)
- [The release](#the-release)
- [A gate that validates one commit](#a-gate-that-validates-one-commit)
- [Why this order](#why-this-order)
- [If something goes wrong](#if-something-goes-wrong)

## Declaring the release<a id="declaring-the-release"></a>

The declaration goes into `.releasing.toml` or `releasing.toml` at the
repository root, or into `[tool.releasing]` of a `pyproject.toml` when the
repository has one that is the project's own:

```toml
repository = "foundata/ansible-skeletons"
ecosystem = "source-repository"
```

That ecosystem sets `index = "none"` and `version-files = []`. A
`pyproject.toml` that only carries development tooling keeps whatever version
it likes; it is not a version site unless `version-files` names it. See
[The release declaration](./config.md) for everything else it can say.

`release config check` prints the effective declaration and fails on a file it
names but cannot find.

## What the release needs<a id="what-the-release-needs"></a>

- `gh` for the GitHub release entry, already authenticated.
- Push access to the remote the release branch tracks.

## Before the release<a id="before-the-release"></a>

Run the project's own checks first. `release` does not replace them and knows
nothing about them.

Decide the version according to [Semantic Versioning](https://semver.org/).

## The release<a id="the-release"></a>

```sh
version="<major.minor.patch>"

# 1. Move the changelog to the new release. There is no version file to bump:
#    the dated section this creates, and the tag, are where the version lives.
release changelog release "${version}"

# 2. Review and commit. The tag will name this commit.
git diff
git add --all
git commit -m "release: prepare ${version}"
git status --short

# 3. Tag the commit, then publish branch and tag together.
release tag create "${version}"
release push "${version}"

# 4. Create the forge release entry from the changelog.
release forge release-create "${version}"

# 5. Verify the remote holds the tag and the forge reports it as latest.
release verify --version "${version}"

# At any point, ask where the release stands.
release status "${version}"
```

`release version check` prints the version the changelog states, so a script
can read it back instead of parsing the file. `release build` and
`release publish` refuse for this ecosystem and say why.

## A gate that validates one commit<a id="a-gate-that-validates-one-commit"></a>

A project whose own gate runs against an exported commit and records which
one passed can bind the tag to that commit:

```sh
release tag create "${version}" --revision "${revision}"
```

The command exports that revision and checks its declaration and changelog
there, refuses a dirty working tree, and refuses a tag that already exists
locally or on the remote. Whether the working tree is at that revision, and
whether the gate's evidence still matches it, stays with the gate that
produced it.

## Why this order<a id="why-this-order"></a>

The changelog moves before the commit, so the commit the tag names already
documents the version and `tag create` can check it there. The push sends the
branch before the tag, so the tag never names a commit the remote has on no
branch. The forge entry is created once and spends the version; `verify` runs
last because it asks what the remote and the forge now serve.

## If something goes wrong<a id="if-something-goes-wrong"></a>

Before the tag is pushed, fix the problem, amend or add a commit and repeat
from the failing step.

After the tag is pushed but before a forge release exists:

```sh
release tag delete "${version}"   # local and remote
```

After a forge release exists, the version is spent: consumers may already
have checked the tag out. Use a new patch version.
