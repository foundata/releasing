# Releasing an Ansible collection

The order below is the one the commands assume. Each step produces a result
the next one depends on, so a skipped step is a missing result rather than a
shortcut.

A collection differs from a Python package in three places: the version lives
in `galaxy.yml`, antsibull-changelog owns the changelog, and the artifact is
one tarball published to Ansible Galaxy. The declaration says so once and
every command follows.

## Declaring the release

A collection has no `pyproject.toml`, so the declaration lives in a
`releasing.toml`, or a `.releasing.toml`, beside `galaxy.yml`:

```toml
repository = "foundata/ansible-collection-example"
ecosystem = "ansible-collection"
```

That ecosystem sets `index = "galaxy"`, `version-files = ["galaxy.yml"]` and
`changelog = "antsibull"`. See [The release declaration](./config.md) for
everything else it can say.

Then keep the declaration out of the artifact, under whichever name it carries.
`ansible-galaxy collection build` reads `build_ignore` in `galaxy.yml` and knows
nothing about `export-ignore`, so a file listed only in `.gitattributes` still
ships. `.git` is the only dotfile the build drops on its own, so a
`.releasing.toml` needs the same entry as a `releasing.toml`:

```yaml
build_ignore:
  - ".gitattributes"
  - "releasing.toml"
```

`release config check` prints the effective declaration and fails on a file it
names but cannot find.

## What the release needs

- `ansible-galaxy`, which builds and publishes the collection.
- `antsibull-changelog`, which owns `changelogs/`. Only
  `release changelog release` calls it; the checks read the file directly.
- `gh` for the GitHub release entry, already authenticated.
- A Galaxy API token for the upload.

## Before the release

Run the project's own gate first: `ansible-lint`, the sanity tests, molecule
and whatever else the collection verifies. `release` does not replace it and
knows nothing about it.

Decide the version according to [Semantic Versioning](https://semver.org/).

## The release

```sh
version="<major.minor.patch>"

# 1. Move the version and the changelog to the new release.
release version bump "${version}"
release changelog release "${version}"

# 2. Review and commit. The tag will name this commit.
git diff
git add --all
git commit -m "release: prepare ${version}"
git status --short

# 3. Build from the committed revision. This prepares the README inside the
#    export, so the Galaxy page shows working links.
release build --out "../dist-${version}" --expect "${version}"

# 4. Tag the revision that was built, then publish branch and tag together.
release tag create "${version}" \
  --manifest "../dist-${version}/artifacts.json"
release push "${version}"

# 5. Publish exactly the file that was validated. ansible-galaxy names the
#    token variable after the server, so the list, the URL and the token
#    belong together; "galaxy" is a label of your choosing.
export ANSIBLE_GALAXY_SERVER_LIST=galaxy
export ANSIBLE_GALAXY_SERVER_GALAXY_URL=https://galaxy.ansible.com/api/
printf 'Galaxy API token: '
read -rs ANSIBLE_GALAXY_SERVER_GALAXY_TOKEN
printf '\n'
export ANSIBLE_GALAXY_SERVER_GALAXY_TOKEN
release publish "../dist-${version}/artifacts.json"
unset ANSIBLE_GALAXY_SERVER_GALAXY_TOKEN

# 6. Create the forge release entry from the changelog and the manifest.
release forge release-create "${version}" \
  --manifest "../dist-${version}/artifacts.json"

# 7. Verify what Galaxy and the forge now serve.
release verify "../dist-${version}/artifacts.json"

# At any point, ask where the release stands.
release status "${version}" --manifest "../dist-${version}/artifacts.json"
```

## The changelog

antsibull-changelog collects fragments and writes
`changelogs/changelog.yaml`; the commands read that file and never edit it.

`release changelog check` needs `--version X.Y.Z` here, because the question
for a collection is whether the file records that release, not whether a
Markdown structure is consistent:

```sh
release changelog check --version "${version}"
```

`release changelog show X.Y.Z` renders the recorded entry as Markdown, with
the section titles set in `changelogs/config.yaml`. That is the same text
`forge release-create` attaches, so the release entry cannot drift from the
changelog. reStructuredText inline literals become code spans; other markup is
passed through as written.

## The README on the Galaxy page

Galaxy renders the collection's `README.md`, where a repository-relative link
resolves against galaxy.ansible.com and breaks. `release build` prepares the
document inside the export, so the shipped README carries absolute URLs at the
version's tag while the committed one keeps the relative links that work on
the forge. Nothing has to be restored afterwards.

A collection whose roles carry their own READMEs can prepare those too; see
`readmes` in [The release declaration](./config.md).

## Why this order

The build runs after the commit and before the tag, so the artifact cannot
contain an uncommitted file. Passing the manifest to `tag create` closes the
window between the two: a commit made in it leaves the tree clean and
`galaxy.yml` correct, so only the manifest's source revision can tell that the
tag would name something no artifact came from.

A version can be uploaded to Galaxy only once, and a published version cannot
be replaced. Step 5 uploads the file whose digest the build recorded and step
7 checks that Galaxy serves that same digest.

## If something goes wrong

Before the tag is pushed, fix the problem and repeat from the failing step;
delete the build directory first, since `build` refuses to write into an
existing one.

After the tag is pushed but before a forge release exists:

```sh
release tag delete "${version}"   # local and remote
```

After a forge release exists, or after the upload, the version is spent. Use a
new patch version.
