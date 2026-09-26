# Version sites

A project states its version in more than one place: `pyproject.toml`, an
`__version__` constant, a `galaxy.yml`, generated JSON. Each such line is a
version site. The declaration's `version-files` lists the files; every listed
file must contain exactly one site, so a file whose spelling drifted fails the
check instead of passing unnoticed.

A site is a line whose key is `version`, `__version__`, `VERSION` or
`"productVersion"`, followed by `=` or `:`, the version, optionally quoted, and
optionally a trailing comma:

```text
version = "1.2.3"
__version__ = "1.2.3"
version: 1.2.3
  "productVersion": "1.2.3",
```

Accepted versions are `X.Y.Z` with an optional pre-release suffix such as
`rc1`, `.dev0` or `-rc.1`.

## Table of contents<a id="toc"></a>

- [`release version check`](#version-check)
- [`release version bump X.Y.Z`](#version-bump)

## `release version check`<a id="version-check"></a>

Prints the one version every site states, or fails naming every
disagreement:

- Sites that state different versions, with file and line.
- A `--expect X.Y.Z` that the sites do not state.
- A `uv.lock` beside the declaration that records another version for a
  declared project; the remedy is `uv lock`.
- A lockstep pin (`dependency-pins`) whose lower bound is not the version.
- In a Git checkout, a release tag on `HEAD` that is not the version's tag.
  Without a checkout, such as in an exported tree, the tag check is skipped.

The check reads files only. In a checkout it also runs `git tag --points-at
HEAD`; nothing is written or fetched.

A project without version sites, such as a `source-repository`, states its
version in the changelog. The command prints the newest released section,
compares `--expect` with it, and still runs the lockfile, pin and tag checks
against that version. Before the first release there is no version to print
and the command fails saying so.

## `release version bump X.Y.Z`<a id="version-bump"></a>

Rewrites every site and raises every lockstep pin's lower bound to the new
version, keeping quoting, spacing, line endings and trailing commas as they
were, then runs `uv lock` when a `uv.lock` exists so the lockfile records the
new version. A unified diff of every rewritten file goes to stderr, with
the rest of the narration. `--dry-run` shows the same diff and writes nothing.

The bump refuses to run while a version file or pinned file has uncommitted
changes, because it rewrites them; `--force` overrides that. Other uncommitted
changes, such as an edited changelog, do not block it. `--no-lock` skips the
lockfile update. The changelog is not touched; see `release changelog`.

A project without version sites has nothing to rewrite. The command refuses
and names `release changelog release X.Y.Z` as the step that moves the
version, since the dated section it creates is where the version lives.
