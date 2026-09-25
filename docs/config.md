# The release declaration

Project-aware `release` commands share one declaration: the facts that differ
between projects, stated once. It lives in `[tool.releasing]` of
`pyproject.toml`. A repository without a `pyproject.toml` uses the same keys at
the top level of a `releasing.toml` beside it, or of a `.releasing.toml` where
the configuration belongs with the other dotfiles. Both names are read and mean
the same thing. Exactly one file may declare it; where two do, the refusal
names them both instead of a search order picking one.

`release config check` loads the declaration, applies every default, verifies
that every file it names exists and prints the effective values. The
`version`, `changelog`, `build`, `tag` and `verify` commands also load and
validate it. Loading never runs Git or another program, so it works in an
exported source tree.

`markdown prepare` and `artifacts verify` run without a declaration.
`artifacts check` and `artifacts manifest` load it only when `--version` is
omitted; supplying that option makes the artifact operations independent of
the project configuration.

## Keys

|          Key          |          Default          | Meaning |
| :-------------------- | :------------------------ | :------ |
| `repository`          | required                  | `owner/name` on the forge. |
| `forge`               | `github`                  | Where tags and releases live. |
| `ecosystem`           | `python`                  | `python`, `ansible-collection` or `hugo-component`; sets other defaults. |
| `index`               | by ecosystem              | `pypi`, `galaxy` or `none`. |
| `version-files`       | by ecosystem              | Files carrying the version, relative to the project root. |
| `changelog`           | by ecosystem              | A Keep a Changelog file, or `antsibull` for antsibull-changelog. |
| `tag-format`          | `v{version}`              | Tag name template; must contain `{version}`. |
| `tag-message`         | `version {version}`       | Annotated tag message; may use `{version}` and `{tag}`. |
| `dependency-pins`     | none                      | Requirements whose lower bound follows the project's version. |
| `readmes`             | one entry for `README.md` | Documents prepared for the index; see below. |
| `allowed-attribution` | none                      | Tool attributions the project carries on purpose; see below. |

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

### `allowed-attribution`

Before `tag create`, `push` and `forge release-create` publish anything, they
read the commits that would become public and that the remote does not have
yet, and refuse a commit whose author or committer is a known tool identity,
whose `Co-authored-by:` names one, that carries an `Assisted-by:` trailer, or
that says it was generated with a tool. A commit message records the work, and
an unpushed message can still be amended for nothing; a published one only
through a history rewrite, which is why the check stops at what the remote
already has.

A project bound by a policy that requires such a disclosure, such as the
[Ansible Community Policy for AI-Assisted Contributions](https://docs.ansible.com/ansible/latest/community/ai_policy.html),
names what it allows here instead of turning the check off. An entry is a rule
name, which allows every value of that rule, or a rule name and a regular
expression, which allows the values that expression finds:

```toml
# Allow the whole rule: any Assisted-by: trailer.
allowed-attribution = ["assisted-by"]

# Or only the values the expression finds, here a disclosure without an
# address. A forge credits a person by the address in the line, so a
# disclosure that names none stays a note in the message.
allowed-attribution = ["assisted-by: ^[^<]*$"]
```

The rules are `identity`, `co-authored-by`, `assisted-by` and
`generated-with`. A pattern is Python's regular-expression syntax, matched
case-insensitively anywhere in the value; it is only ever compiled, never run
as a command, and an expression that does not compile is a declaration error
rather than a rule that silently matches nothing. An entry naming an unknown
rule is refused for the same reason.

`--allow-tool-attribution` permits everything for one invocation and names in
a warning what it let through.

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

An Ansible collection, in `releasing.toml` (or `.releasing.toml`):

```toml
repository = "foundata/ansible-collection-linux"
ecosystem = "ansible-collection"

[[readmes]]
collapse-header = true
simplify-badges = true

[[readmes]]
source-path = "roles/auto_update/README.md"
```
