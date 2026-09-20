# Releasing a Python package

The order below is the one the commands assume. Each step produces a result
the next one depends on, so a skipped step is a missing result rather than a
shortcut.

The project needs a release declaration; see
[The release declaration](./config.md). Add `releasing` to a development
dependency group, then run the commands with `uv run release ...`.

## Before the release

Run the project's own gate first: formatting, linting, type checks, the test
matrix and whatever else the project verifies. `release` does not replace it
and knows nothing about it.

Decide the version according to [Semantic Versioning](https://semver.org/).

## The release

```sh
version="<major.minor.patch>"

# 1. Move the version and the changelog to the new release.
uv run release version bump "${version}"
uv run release changelog release "${version}"

# 2. Review and commit. The tag will name this commit.
git diff
git add --all
git commit -m "release: prepare ${version}"
git status --short

# 3. Build from the committed revision. This prepares the README inside the
#    export, so the working tree keeps its relative links.
uv run release build --out "../dist-${version}" --expect "${version}"

# 4. Tag the revision that was built, then publish branch and tag together.
uv run release tag create "${version}" \
  --manifest "../dist-${version}/artifacts.json"
uv run release push "${version}"

# 5. Publish exactly the files that were validated.
printf 'PyPI API token: '
read -rs UV_PUBLISH_TOKEN
printf '\n'
export UV_PUBLISH_TOKEN
uv run release publish "../dist-${version}/artifacts.json"
unset UV_PUBLISH_TOKEN

# 6. Create the forge release entry from the changelog and the manifest.
uv run release forge release-create "${version}" \
  --manifest "../dist-${version}/artifacts.json"

# 7. Verify what the index and the forge now serve.
uv run release verify "../dist-${version}/artifacts.json"

# At any point, ask where the release stands.
uv run release status "${version}" --manifest "../dist-${version}/artifacts.json"
```

## Why this order

The build runs after the commit and before the tag. Building from the commit
means the artifacts cannot contain an uncommitted file, and the README
preparation happens inside the export, so the committed README keeps the
relative links that work on the forge.

Tagging after the build means a build that fails leaves no tag to delete.
Passing the manifest to `tag create` closes the window between the two: a
commit made in it leaves the tree clean and the version sites correct, so only
the manifest's source revision can tell that the tag would name something no
artifact came from.

While no forge release exists, `release tag delete` can still remove a tag
that named the wrong revision; after the release is created, the version is
spent and the fix needs a new one.

A version can be uploaded to PyPI only once. A broken release cannot be
replaced, only [yanked](https://pypi.org/help/#yanked), so step 5 uploads the
files whose digests the build recorded and step 7 checks that the index serves
those same bytes.

## Workspaces

A repository releasing several packages in lockstep declares every member's
version file, the requirement whose lower bound follows the version, and the
member READMEs the prepared project README is copied over:

```toml
[tool.releasing]
repository = "foundata/example"
version-files = [
  "packages/example/pyproject.toml",
  "packages/example-gui/pyproject.toml",
]
dependency-pins = [
  { file = "packages/example-gui/pyproject.toml", name = "example" },
]

[[tool.releasing.readmes]]
copies = ["packages/example/README.md", "packages/example-gui/README.md"]
```

`version bump` then raises the pin with the version, and `version check`
fails when a member falls behind. A new major version still needs the upper
bound of the pin raised by hand.

## If something goes wrong

Before the tag is pushed, fix the problem and repeat from the failing step;
delete the build directory first, since `build` refuses to write into an
existing one.

After the tag is pushed but before a forge release exists:

```sh
uv run release tag delete "${version}"   # local and remote
```

After a forge release exists, or after the upload, the version is spent. Use a
new patch version.
