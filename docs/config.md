# The release declaration

Every `release` command reads one declaration per project: the facts that
differ between projects, stated once. It lives in `[tool.releasing]` of
`pyproject.toml`. A repository without a `pyproject.toml` uses the same keys at
the top level of a `releasing.toml` beside it. Exactly one of the two must
declare it.

`release config check` loads the declaration, applies every default, verifies
that every file it names exists and prints the effective values. Every other
command runs the same check first. Loading never runs Git or another program,
so it works in an exported source tree.

## Keys

|        Key        |          Default          | Meaning |
| :---------------- | :------------------------ | :------ |
| `repository`      | required                  | `owner/name` on the forge. |
| `forge`           | `github`                  | Where tags and releases live. |
| `ecosystem`       | `python`                  | `python`, `ansible-collection` or `hugo-component`; sets other defaults. |
| `index`           | by ecosystem              | `pypi`, `galaxy` or `none`. |
| `version-files`   | by ecosystem              | Files carrying the version, relative to the project root. |
| `changelog`       | by ecosystem              | A Keep a Changelog file, or `antsibull` for antsibull-changelog. |
| `tag-format`      | `v{version}`              | Tag name template; must contain `{version}`. |
| `tag-message`     | `version {version}`       | Annotated tag message; may use `{version}` and `{tag}`. |
| `dependency-pins` | none                      | Requirements whose lower bound follows the project's version. |
| `readmes`         | one entry for `README.md` | Documents prepared for the index; see below. |

Ecosystem defaults:

|      Ecosystem       | `index`  |   `version-files`    | `changelog` |
| :------------------- | :------- | :------------------- | :---------- |
| `python`             | `pypi`   | `["pyproject.toml"]` | `CHANGELOG.md` |
| `ansible-collection` | `galaxy` | `["galaxy.yml"]`     | `antsibull` |
| `hugo-component`     | `none`   | `[]`                 | `CHANGELOG.md` |

Unknown keys are rejected, so a misspelled key cannot silently fall back to a
default. Paths must be relative, inside the project and without `..`.

### `readmes`

An array of tables, one per document that ships in an artifact:

|        Key        |      Default      | Meaning |
| :---------------- | :---------------- | :------ |
| `source-path`     | `README.md`       | The document's path relative to the project root. |
| `ref`             | `refs/tags/{tag}` | Git ref used in the rewritten URLs; may use `{version}` and `{tag}`. |
| `simplify-badges` | `false`           | Replace linked Markdown images with text links. |
| `collapse-header` | `false`           | Collapse the `project-readme-header` block into one line. |
| `copies`          | none              | Paths the prepared document is copied to inside the export. |

The tag ref is the default because the index page of version X should link to
the files of version X. The tag is pushed with the release, or the artifacts are
never uploaded.

### `dependency-pins`

An array of tables with `file` and `name`. On a version bump, the lower bound
of the named requirement in that file is raised to the new version. This
encodes a lockstep release of workspace members, such as a frontend package
that requires its own engine version or newer.

## Examples

A single-package Python project:

```toml
[tool.releasing]
repository = "foundata/ansible-docsmith"
version-files = ["pyproject.toml", "src/ansible_docsmith/__init__.py"]
```

A uv workspace releasing two packages in lockstep:

```toml
[tool.releasing]
repository = "foundata/scanmole"
version-files = [
  "packages/scanmole/pyproject.toml",
  "packages/scanmole-gui/pyproject.toml",
]
dependency-pins = [
  { file = "packages/scanmole-gui/pyproject.toml", name = "scanmole" },
]

[[tool.releasing.readmes]]
copies = ["packages/scanmole/README.md", "packages/scanmole-gui/README.md"]
```

An Ansible collection, in `releasing.toml`:

```toml
repository = "foundata/ansible-collection-linux"
ecosystem = "ansible-collection"

[[readmes]]
collapse-header = true
simplify-badges = true

[[readmes]]
source-path = "roles/auto_update/README.md"
```
