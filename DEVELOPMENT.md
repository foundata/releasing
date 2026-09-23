# Developing release helpers

The repository is the `releasing` Python package: the `release` command and
the `releasing` import package under `src/`. One module per release step, with
`markdown`, `changelog`, `version`, `config` and `artifacts` free of Git,
network and subprocess use so they also work inside an exported tree. Python
3.11 to 3.14 are supported; the 3.11 floor exists for consumers that target
Debian 12. Use `uv` for development environments and for running the command.

## Glossary

Vocabulary that recurs in the code and the docs and does not explain itself
from `--help`.

- **Forge**: where the source lives. It owns the tags, the release entries and
  the URLs a prepared README points at. GitHub today; the `forge` key selects
  it.
- **Index**: where an artifact is published. PyPI or Ansible Galaxy; the
  `index` key selects it, and `none` means the project publishes no artifact.
- **Ecosystem**: which build tool and which defaults apply, `python`,
  `ansible-collection` or `hugo-component`. It sets `index`, `version-files`
  and the changelog format unless the declaration overrides them.
- **Declaration**: the `[tool.releasing]` table in `pyproject.toml`, or the
  same keys at the top level of a `releasing.toml`. Every project-aware command
  reads it; see [The release declaration](./docs/config.md).
- **Version site**: one line in a declared file that states the version, such
  as `version = "1.2.3"` in `pyproject.toml` or `galaxy.yml`. Every declared
  file must contain exactly one.
- **Manifest**: `artifacts.json`, the list of files a build validated with
  their SHA-256 digests, the version and the revision they came from. It
  decides what is uploaded and what is compared afterwards.

A published artifact takes its name from the packaging metadata on the index
side, never from the repository it was built in. The forge name and the
published name are allowed to differ, and usually do:

|             Repository (forge)             |             Packaging metadata              | Published as |
| :----------------------------------------- | :------------------------------------------ | :----------- |
| `foundata/releasing`                       | `[project] name = "releasing"`              | `releasing-4.1.0-py3-none-any.whl` |
| `foundata/ansible-docsmith`                | `[project] name = "ansible-docsmith"`       | `ansible_docsmith-2.2.0-py3-none-any.whl` |
| `foundata/scanmole`                        | two members, `scanmole` and `scanmole-gui`  | `scanmole-1.2.0.tar.gz` and `scanmole_gui-1.2.0.tar.gz` |
| `foundata/ansible-collection-apache-httpd` | `namespace: foundata`, `name: apache_httpd` | `foundata-apache_httpd-1.3.0.tar.gz` |

A Python distribution therefore has three spellings: the install name
(`ansible-docsmith`), the file name (`ansible_docsmith-...`, escaped by
PEP 427) and the import name (`ansible_docsmith`). PyPI treats runs of `-`,
`_` and `.` as equal, so `verify` normalizes them there; a collection name
cannot contain a hyphen, so `foundata-apache_httpd` splits back at the first
one without ambiguity.


## Setup and checks

```sh
uv sync --frozen --python 3.11
uv run --frozen ruff format --check .
uv run --frozen ruff check .
uv run --frozen mypy
uv run --frozen python tests/check_markdown.py
uv run --frozen pytest --cov --cov-report=term-missing
uv run --frozen --python 3.11 pytest
uv run --frozen --python 3.12 pytest
uv run --frozen --python 3.13 pytest
uv run --frozen --python 3.14 pytest
git diff --check
```

Run these commands sequentially: selecting another Python version replaces the
development environment. The checks are local and include real builds of
temporary sample projects and workspaces. They do not upload artifacts, run
other projects' release gates or change other projects.

Apply Python lint fixes before formatting:

```sh
uv run --frozen ruff check --fix .
uv run --frozen ruff format .
uv run --frozen python tests/check_markdown.py --format
```

The Markdown check uses the exact foundata guide flags, with no local
configuration. `tests/unit/test_dependencies.py` compares that copy with the
guide's own invocation whenever the guidelines are checked out beside this
repository, or at `FOUNDATA_GUIDELINES`, and skips where they are not. It
targets the README, the command documentation under `docs/` and the
commit-review documentation in `tools/`. Corpus snapshots and their expected
output are deliberately excluded: formatting them would invalidate the
comparison.

## Shell checks

For `tools/git-review-unpushed.sh`, use the foundata shell guide's exact checks:

```sh
shfmt --language-dialect posix --indent 2 --case-indent --binary-next-line --simplify --diff tools/git-review-unpushed.sh
shellcheck --shell=sh --severity=style --exclude=SC2292 --exclude=SC3040 --exclude=SC3043 --enable=all tools/git-review-unpushed.sh
checkbashisms tools/git-review-unpushed.sh
dash -n tools/git-review-unpushed.sh
bash -n tools/git-review-unpushed.sh
uv run --frozen pytest tests/integration/test_git_review.py
```

Use the same shfmt flags with `--write` instead of `--diff` to format the
script. These tools are development requirements, not new runtime dependencies.
The terminal-driven regression tests use isolated Git configuration, temporary
repositories and local filesystem remotes. Git transport is restricted to local
files in the test environment. Tests never fetch real project remotes or push.
They exercise both Dash and Bash; a missing shell is reported as a skipped
compatibility check.

## Checking on Windows

The package supports Windows and the suite passes there: 714 passed and 19
skipped on Windows Server 2025 with Python 3.14, measured on 2026-09-23. No
development or release step needs Windows; a Linux run covers every test.

Most of what differs between platforms is a parameter rather than a machine.
`reporting.program()`, `reporting.render()` and `reporting.wants_colour()` take
`platform=`, so both sets of rules are asserted from any host: the name a
program is echoed under, the quoting of a command line, and the console's veto
over colour. What stays native is `_enable_windows_sequences()`, which calls
the Windows console API; only a run there covers it.

Run the suite on Windows before releasing a change to `reporting`, `processes`
or `_source_export`. Any Windows host with Git and uv will do, reached however
you reach one. The work does not have to be pushed first:

```sh
git bundle create ../releasing.bundle main
```

Copy that bundle to the host by any means, then, on the host:

```sh
git clone --branch main releasing.bundle releasing
cd releasing
uv sync --frozen --python 3.14
uv run --frozen pytest -q
```

Three things decide whether that run means anything:

- Git and uv must be on `PATH`. The suite starts both as subprocesses, and a
  missing one appears as dozens of fixture errors rather than as a failure.
- Python 3.11 to 3.13 cannot create the environment there, because
  `readme-renderer[md]` pulls `comrak`, which publishes Windows wheels for
  cp314 only. That is a development dependency; the package itself supports
  every declared version on that platform.
- The POSIX-only tests skip, and the shell-review module skips as a whole for
  want of a pseudo-terminal. A clean run reports skips, never errors.

## Dependencies

The direct runtime dependencies are `markdown-it-py` and `typing-extensions` on
every supported Python version. The latter supplies the `override` decorator
through one unconditional import, including on Python 3.11. Everything else
comes from the standard library, including the archive, JSON, hashing and HTTP
handling. Every question put to a forge or a package index goes through the
`fetch` module, so one place decides how a request is made: a revalidated GET, a
bounded wait and one narrated line per request. The parser decides which text is
a link, reference definition, code block, code span or HTML region. The private
`_markdown_syntax` module owns its rule adapter, source coordinates and analysis
records. It constructs the parser and document for each call and imports no
release-step module.

`markdown` uses those records for URL rewriting, simplification and optional
local-file validation. It retains the public analysis imports alongside
`prepare_markdown` and `validate_local_files`. Edits replace destinations in
the original source; the document is never serialized from its syntax tree.
CLI file replacement and build-workspace cleanup stay with their callers.

The adapter uses the parser's rule API, so the dependency is bounded below the
next major version and a test checks that the installed parser satisfies the
declared range. The suite passes against `markdown-it-py` 3.0.0 and every 4.x
release; run it against the oldest and newest supported parser after changing
the range, then update the lockfile explicitly with `uv lock`. The
development-only `readme-renderer[md]` dependency supplies an independent
publishing renderer. Twine is neither required nor installed.

## Coverage

```sh
uv run --frozen pytest --cov --cov-report=term-missing
```

Coverage is measured only for the modules whose tests exercise them in the same
process, and the threshold is 90%. The command-line layer and everything that
drives Git, uv or a forge is tested by running the real command in a
subprocess, which coverage cannot observe: `build.py` reports 17% although
`tests/integration/test_build.py` performs real exports, real builds and real
manifest checks. Counting those files would produce a number that says nothing
about how well they are tested, and a threshold on it would reward replacing
end-to-end tests with weaker in-process ones. `pyproject.toml` lists the
excluded files.

Measuring the subprocesses is possible in principle, with coverage's parallel
mode and its start-up hook, but the child processes then write `.coverage`
files into the trees under test, which breaks the assertions that a build
leaves the working tree untouched. That trade is not worth a metric.

## Test layout

- `tests/unit/`: fixture transformations, parser boundaries and validation
  errors.
- `tests/integration/`: command-line behaviour, temporary Git repositories,
  real builds and independent rendering checks.
- `tests/integration/test_reporting.py`: the stream contract. Stdout carries
  the product, stderr the story, `--quiet` drops the story but never an error,
  a dry run changes nothing, and a library caller narrates nothing at all.
- `tests/fixtures/cases.json`: small reviewed inputs and exact expected output.
- `tests/fixtures/mixed-content*.md`: nested containers, references, tables,
  HTML, code and comments with exact expected Markdown and renderer assertions.
- `tests/fixtures/corpus/`: 21 project README snapshots, the reviewed expected
  output of both modes and their provenance.

Tests that need a symbolic link, a device file, a permission bit or a path
Windows cannot name carry `POSIX_ONLY` from `tests/support.py` and skip
elsewhere. Fixtures are written through `write_lf()`, because Python ends a line
with CRLF on Windows and a fixture written that way would put those bytes into
the commit a test reads back. Output is compared through `captured()`, which
reads a captured stream as text with the platform's line endings normalized,
because Python ends a line with CRLF on Windows; the paths whose exact bytes are
the contract are still compared as bytes.

Tests import the installed package (`uv sync` installs it in editable mode)
and use temporary directories; they never edit checked-in fixtures. The complete
suite requires Git and `uv`, but no network, existing Git checkout or sibling
repository. Dash is also needed for the full
commit-review compatibility matrix. Pure transformation tests can run
separately:

```sh
uv run --frozen pytest tests/unit
```

CLI tests run `python -I -m releasing markdown prepare` with an empty program
search path, proving that transformation does not invoke Git or external
programs. They cover input preservation, strict
failure before any write, stdout purity, encoding failures, aliases, atomic
replacement and permission preservation. Renderer tests examine actual HTML link
and image destinations, including screenshot dimensions; successful parsing
alone is not the assertion.

Combination tests place identical active and literal link syntax in nested
lists, block quotes and tables, across LF, CRLF and CR line endings. They check
exact output and idempotence. Simplification tests cover the independent flags
and their equivalence to `-s`.

Dry-run tests verify diffs, exit statuses and unchanged contents, modes, inodes
and timestamps. Local-file checks use disposable directory trees, including
encoded paths, directory links, missing files, symlinks and special files. They
never require destination files from sibling projects or contact remote URLs.

## Corpus maintenance

Snapshots cover `conclear`, `ansible-docsmith`, `scanmole` and all 18 local
`oci-*-itt` repositories. `manifest.json` records each repository's source
revision, the README SHA-256 and whether it matches that revision. The current
output matches every frozen expectation in both modes, with no corpus
exceptions.

The expectations are a change detector, not the authority on correctness. They
were first produced by the shell script this package replaces, then audited
against the current rules: none of the 42 files contains a repository-relative
destination, and the current implementation reproduces each one exactly. What
establishes correctness is separate. `tests/fixtures/cases.json` and the
mixed-content fixtures cover the behaviour that deliberately departs from the
old shell script, and the renderer tests prepare each corpus README afresh and
assert on the rendered HTML without consulting the frozen files. Changing an
expectation is therefore a deliberate fixture change, reviewed in the commit
that changes the behaviour.

To deliberately refresh the snapshots from a directory containing those
repositories:

```sh
uv run --frozen python tests/corpus.py --refresh-from /path/to/foundata
uv run --frozen pytest
```

The refresh reads working-tree READMEs and regenerates the expected output.
Review all resulting fixture changes. A working-tree snapshot that
differs from its recorded commit is identified in the manifest rather than
presented as committed content. Changes in corpus membership require updating
the coverage assertion.

## Releases

A release of this package consists of:

- one Semantic Versioning `X.Y.Z` version
- one annotated `vX.Y.Z` Git tag
- one GitHub release for that tag
- the source distribution and the wheel published on PyPI for that version.

The maintainer performing a release needs an authenticated `gh` installation,
an authorized PyPI publishing identity and push access to `origin`.

The package releases itself: every `release` command below runs this working
tree's own code through its editable install, so a defect in the release path
shows up here before it reaches a consumer. The declaration is the
`[tool.releasing]` table in `pyproject.toml`; it names the repository only,
because the version lives in `pyproject.toml` alone and `releasing.__version__`
reads it from the installed distribution metadata. There is no second version
site to edit.

Release only a clean, committed revision. The build output goes to a temporary
directory. Step 7 attaches the manifest and both distributions to the GitHub
release and PyPI serves the same bytes, so nothing in that directory needs
keeping once step 8 passes.

1. **Run the checks and decide the version.** Everything under "Setup and
   checks" and "Shell checks" must pass on all supported Python versions
   before a release starts.

   ```sh
   version="<FIXME version>" # major.minor.patch

   git status --short
   uv run --frozen release config check
   uv run --frozen release version check
   uv run --frozen release changelog check
   ```

   Follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html) against
   what consumers depend on: the command surface, the exit statuses, the
   manifest format and the release declaration. A check that starts rejecting
   input it used to accept is a major version, even when the rejection is the
   fix.

2. **Move the version and the changelog to the new release.**

   ```sh
   uv run --frozen release version bump "${version}"
   uv run --frozen release changelog release "${version}"

   uv run --frozen release version check --expect "${version}"
   uv run --frozen release changelog check
   ```

   `version bump` rewrites the version in [`pyproject.toml`](./pyproject.toml)
   and runs `uv lock`, so the lockfile records it too. `changelog release`
   turns the entries under `Unreleased` in [`CHANGELOG.md`](./CHANGELOG.md)
   into a dated section and updates the comparison links at the end of the
   file.

   Then review the documentation the release changes: the command list in
   [`README.md`](./README.md), the page under `docs/` for each new or changed
   command, and this procedure when it moved.

3. **Review and commit the release preparation.** The tag will name this
   commit.

   ```sh
   git diff --check
   git diff
   git add --all
   git commit -m "release: prepare ${version}"

   revision="$(git rev-parse --verify HEAD)"
   git status --short # must print nothing
   ```

4. **Build from the committed revision.**

   ```sh
   dist="${TMPDIR:-/tmp}/releasing-${version}/dist"
   mkdir -p "$(dirname "${dist}")"

   uv run --frozen release build --out "${dist}" --expect "${version}"
   ```

   The build exports the commit with `git archive` and prepares `README.md`
   inside that export, so the committed README keeps the relative links that
   work on GitHub and the working tree is never modified. The source
   distribution is built from the export and the wheel from that source
   distribution; both are checked, and their SHA-256 digests are recorded in
   `artifacts.json`. The destination itself must not exist beforehand, so a
   repeat needs `rm -rf "${dist}"` first. The path is predictable rather than
   random, so the remaining steps can be retyped in another shell.

5. **Tag the revision that was built, then publish branch and tag.**

   ```sh
   uv run --frozen release tag create "${version}" \
     --manifest "${dist}/artifacts.json"
   git show "v${version}"
   uv run --frozen release push "${version}"
   ```

   `tag create` refuses a dirty working tree, a version that the declaration,
   the lockfile and the changelog do not all state, or a revision other than
   the one the manifest's artifacts were built from. `push` sends
   the branch first and the tag second, and refuses when the branch does not
   contain the tagged commit.

   While no GitHub release exists, a tag that named the wrong revision can
   still be removed and the procedure restarted from step 3:

   ```sh
   uv run --frozen release tag delete "${version}"
   ```

6. **Publish the validated files to PyPI.** Keep a token out of shell history
   and process arguments:

   ```sh
   printf 'PyPI API token: '
   read -rs UV_PUBLISH_TOKEN
   printf '\n'
   export UV_PUBLISH_TOKEN

   uv run --frozen release publish "${dist}/artifacts.json"

   unset UV_PUBLISH_TOKEN
   ```

   `publish` re-checks every digest against the bytes on disk and uploads
   exactly the files the manifest names, so an unvalidated file beside them is
   a refusal rather than an extra upload. A version can be uploaded only once.
   A broken release cannot be replaced, only
   [yanked](https://pypi.org/help/#yanked), and the fix needs a new version.

7. **Create the GitHub release.**

   ```sh
   uv run --frozen release forge release-create "${version}" \
     --manifest "${dist}/artifacts.json"
   ```

   The notes are the changelog section for the version and the attached files
   are the ones already published, both taken from sources that cannot drift
   from what was validated. The write goes through `gh`, which owns the
   authenticated session.

8. **Verify what PyPI and GitHub now serve.**

   ```sh
   uv run --frozen release verify "${dist}/artifacts.json" \
     --version "${version}"

   uv run --frozen release status "${version}" \
     --manifest "${dist}/artifacts.json"

   rm -rf "${TMPDIR:-/tmp}/releasing-${version}"
   ```

   `verify` answers three questions: does PyPI serve files for this version
   whose digests match the manifest, does an isolated install of that version
   report it, and does GitHub report the tag as the latest release. `status`
   reports the same release as six separate steps and exits non-zero while any
   of them is unfinished, which is also how to resume after an interruption at
   any point above.

If the temporary directory is lost mid-release, repeat step 4 while nothing has
been uploaded yet. After the upload, fetch the published files into `${dist}`
and record them there instead, then continue with step 7:

```sh
uv run --frozen release artifacts manifest \
  "${dist}"/*.tar.gz "${dist}"/*.whl \
  --revision "${revision}" --out "${dist}/artifacts.json"
```

Consuming projects pin `releasing` in a development dependency group and pick
the new version up with `uv lock --upgrade-package releasing`. A major version
additionally needs their declared upper bound raised by hand.

## Licensing and commits

New Python files use the foundata copyright and `GPL-3.0-or-later` SPDX headers.
`REUSE.toml` supplies scoped annotations for metadata, documentation and
fixtures, including the unmodified foundata README snapshots. The GPL text is in
`LICENSES/`.

Use one scoped subject line, such as
`markdown: preserve fragments in prepared links`, and no body unless the
motivation cannot be recovered from the diff. Keep directly related tests and
documentation with the behaviour change. Follow the foundata Python, Markdown
and Git commit guides.
