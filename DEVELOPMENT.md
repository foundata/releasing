# Developing release helpers

The repository is the `releasing` Python package: the `release` command and
the `releasing` import package under `src/`. One module per release step, with
`markdown`, `changelog`, `version`, `config` and `artifacts` free of Git,
network and subprocess use so they also work inside an exported tree. Python
3.11 to 3.14 are supported; the 3.11 floor exists for consumers that target
Debian 12. Use `uv` for development environments and for running the command.

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
configuration. It targets the README, the command documentation under `docs/`
and the commit-review documentation in `tools/`. Corpus snapshots and their
expected output are deliberately excluded: formatting them would invalidate the
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

## Dependencies

The direct runtime dependencies are `markdown-it-py` and `typing-extensions`
on every supported Python version. The latter supplies the `override`
decorator through one unconditional import, including on Python 3.11.
Everything else comes from the standard library, including the archive, JSON,
hashing and HTTP handling. The parser decides which text is a link, reference
definition, code block, code span or HTML region. The private
`_markdown_syntax` module owns its rule adapter, source coordinates and
analysis records. It constructs the parser and document for each call and
imports no release-step module.

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
- `tests/fixtures/cases.json`: small reviewed inputs and exact expected output.
- `tests/fixtures/mixed-content*.md`: nested containers, references, tables,
  HTML, code and comments with exact expected Markdown and renderer assertions.
- `tests/fixtures/corpus/`: 21 project README snapshots, the reviewed expected
  output of both modes and their provenance.

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
