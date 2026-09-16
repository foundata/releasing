# Developing the Markdown transformer

The repository keeps its standalone release helpers. The Markdown transformer is
one Python script with inline dependency metadata; this repository is not
published as a Python package. Python 3.12, 3.13 and 3.14 are supported. Use
`uv` for development environments and script execution.

## Setup and checks

```sh
uv sync --frozen --python 3.12
uv run --frozen ruff format --check .
uv run --frozen ruff check .
uv run --frozen mypy
uv run --frozen python tests/check_markdown.py
uv run --frozen --python 3.12 pytest
uv run --frozen --python 3.13 pytest
uv run --frozen --python 3.14 pytest
git diff --check
```

Run these commands sequentially: selecting another Python version replaces the
development environment. They only run local checks. There are no builds,
release gates, uploads or changes to other projects.

Apply Python lint fixes before formatting:

```sh
uv run --frozen ruff check --fix .
uv run --frozen ruff format .
uv run --frozen python tests/check_markdown.py --format
```

The Markdown check uses the exact foundata guide flags, with no local
configuration. It targets the transformer documentation. Corpus snapshots and
expected output are deliberately excluded: formatting them would invalidate the
comparison. Other helpers and their documentation are outside this change.

## Dependencies

`markdown-it-py` is the only direct runtime dependency. The parser decides which
text is a link, reference definition, code block, code span or HTML region. A
small adapter records source positions through its parsing rules; edits replace
destinations in the original source. The document is never serialized from its
syntax tree.

The parser is pinned because the adapter uses its rule API. Its version appears
in both `pyproject.toml` and the script's inline metadata; a test checks that
they agree. Review parser changes and run the complete suite when updating it.
Update both lockfiles explicitly:

```sh
uv lock
uv lock --script release-prepare-markdown.py
```

`uv.lock` pins development tools. `release-prepare-markdown.py.lock` pins
standalone script execution. The development-only `readme-renderer[md]`
dependency supplies an independent publishing renderer. Twine is neither
required nor installed.

## Test layout

- `tests/unit/`: fixture transformations, parser boundaries and validation
  errors.
- `tests/integration/`: CLI file operations, shell comparisons and independent
  rendering checks.
- `tests/fixtures/cases.json`: small reviewed inputs and exact expected output.
- `tests/fixtures/corpus/`: 21 project README snapshots, both shell outputs and
  provenance.

Tests use temporary directories and never edit checked-in fixtures. The complete
suite requires Bash and the shell baseline's Unix tools, but no network, Git
checkout or sibling repository. Pure transformation tests can run separately:

```sh
uv run --frozen pytest tests/unit
```

CLI tests run with an empty program search path, proving that transformation
does not invoke Git or external programs. They cover input preservation, strict
failure before any write, stdout purity, encoding failures, aliases, atomic
replacement and permission preservation. Renderer tests examine actual HTML link
and image destinations, including screenshot dimensions; successful parsing
alone is not the assertion.

## Corpus maintenance

Snapshots cover `conclear`, `ansible-docsmith`, `scanmole` and all 18 local
`oci-*-itt` repositories. `manifest.json` records each repository's source
revision, the README SHA-256 and whether it matches that revision. It also
records the unchanged shell script's SHA-256. The current Python output matches
every frozen shell output in both modes, with no corpus exceptions.

To deliberately refresh the snapshots from a directory containing those
repositories:

```sh
uv run --frozen python tests/corpus.py --refresh-from /path/to/foundata
uv run --frozen pytest
```

The refresh reads working-tree READMEs and runs the shell only on temporary
copies. Review all resulting fixture changes. A working-tree snapshot that
differs from its recorded commit is identified in the manifest rather than
presented as committed content. Changes in corpus membership require updating
the coverage assertion.

## Licensing and commits

New Python files use the foundata copyright and `GPL-3.0-or-later` SPDX headers.
`REUSE.toml` supplies scoped annotations for metadata, documentation and
fixtures, including the unmodified foundata README snapshots. The GPL text is in
`LICENSES/`. These annotations do not change licensing metadata on unrelated
legacy helpers.

Use concise scoped commit subjects, such as
`markdown: preserve fragments in prepared links`. Keep directly related tests
and documentation with the behavior change. Follow the foundata Python, Markdown
and Git commit guides.
