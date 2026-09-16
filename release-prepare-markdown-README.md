# Preparing Markdown for package indexes

`release-prepare-markdown.py` rewrites repository-relative Markdown and HTML
destinations to absolute URLs. It preserves the document around those
destinations, including HTML image dimensions. Use it on a temporary copy or
write a separate output file. The shell script remains available and unchanged.

## Running the script

The script supports Python 3.12 through 3.14. Its only direct runtime dependency
is `markdown-it-py`, declared in inline script metadata. `uv` manages the
environment; no package installation into the system Python is needed.

```sh
uv run --frozen --script ./release-prepare-markdown.py \
  -o foundata -r example --ref refs/tags/v1.0.0 \
  --strict --output /tmp/example-pypi.md ./README.md
```

Keep the script's adjacent `.py.lock` file for frozen execution. Dependency
setup may need network access on the first run. Transformation itself is
offline, non-interactive and deterministic for the same input and arguments. It
never invokes Git or consults `.git`.

Write Markdown to stdout instead:

```sh
uv run --frozen --script ./release-prepare-markdown.py \
  -o foundata -r example --ref refs/tags/v1.0.0 \
  --strict --stdout ./README.md
```

`--output -` is equivalent to `--stdout`. Both require one input. Stdout
contains only the transformed Markdown; diagnostics go to stderr. Out-of-place
operation requires explicit organization and repository names, or both custom
URL bases. The output must not alias the input, including through a hard link or
symlink.

## Existing in-place usage

The old positional-file interface remains available, including multiple files:

```sh
uv run --frozen --script ./release-prepare-markdown.py \
  -b main -o foundata -r example ./README.md ./CHANGELOG.md
```

`--in-place` makes that default mode explicit. In this mode only, omitted
organization and repository names default to the current directory's parent name
and current directory name. The branch defaults to `main`. A changed file
produces a unified diff on stderr. Unchanged files are not replaced. Changed
files are replaced atomically while retaining permissions. In-place symlink
inputs are refused.

All inputs are read and transformed before any file is written, so a strict
validation failure leaves the complete batch unchanged. A later filesystem
failure can leave earlier successful replacements in place; multi-file writes
are not a filesystem transaction.

The shell remains callable with its existing interface:

```sh
./release-prepare-markdown.sh -b main -o foundata -r example ./README.md
```

## Branches, tags and source paths

`-b` / `--branch` accepts a branch name. `--ref` accepts `refs/heads/NAME`,
`refs/tags/NAME`, or a full commit SHA. The options are mutually exclusive. Use
an explicit commit SHA when links must identify an exact source revision; tags
remain subject to repository tag-management policy. No ref is resolved or
checked remotely.

For `-b main`, the default bases retain the shell's spelling:

- Images: `https://raw.githubusercontent.com/ORG/REPO/refs/heads/main/`.
- Links: `https://github.com/ORG/REPO/blob/main/`.

With `--ref`, the supplied ref is used in both bases. Ordinary Markdown links
use the GitHub file viewer even when the destination is a PDF, archive or image.
Markdown images use raw URLs regardless of extension. HTML `href` uses the UI
base; `src` and `poster` use the raw base.

`--source-path` is the input document's path relative to the repository root. It
defaults to `README.md`, regardless of the input or output filesystem location.
Set it when transforming a document from a subdirectory:

```sh
uv run --frozen --script ./release-prepare-markdown.py \
  -o foundata -r example --ref refs/tags/v1.0.0 \
  --source-path docs/README.md --strict \
  --output /tmp/example-docs.md ./docs/README.md
```

Here `../LICENSES/GPL-3.0-or-later.txt` resolves from `docs/` to the repository
root. Moving the output into a package directory does not change that
resolution. `--source-path` requires a single input.

For another forge or custom routing, supply both bases. Trailing slashes are
normalized:

```sh
uv run --frozen --script ./release-prepare-markdown.py \
  -a https://gitlab.example/org/repo/-/raw/v1.0.0/ \
  -u https://gitlab.example/org/repo/-/blob/v1.0.0/ \
  --strict --output /tmp/example.md ./README.md
```

## Supported transformations

The parser uses CommonMark. Supported destinations include inline links and
images, titled or angle-bracketed destinations, balanced or escaped parentheses,
nested images inside links, and reference-style definitions. Fragments and
queries are retained. Repository paths are normalized and URL-encoded where
necessary.

Reference definitions retain their labels, titles and layout. Definitions used
by images get the raw base; other definitions get the UI base. A definition
shared by a link and an image uses the raw base so that the image loads. Unused
and duplicate definitions are also prepared.

HTML attributes are parsed as HTML. Quoting, spacing, tag spelling and unrelated
attributes are preserved. Attributes such as `data-src` are not treated as
`src`. HTML comments, fenced and indented code blocks, inline code spans,
external URLs, autolinks and local `#anchors` remain unchanged. Line endings and
the presence or absence of a final newline are preserved during destination
rewriting.

This is not a Markdown formatter, HTML sanitizer or remote link checker. It does
not resolve refs, check file existence, fetch URLs or promise to understand
every publishing extension. GFM tables in the corpus are covered by the
independent publishing-renderer tests; arbitrary extensions require their own
fixtures.

## Strict validation

`--strict` fails if a parsed repository-relative destination cannot be resolved,
such as a root-relative `/docs/file.md` or a `../` path escaping the repository.
Diagnostics identify the input file and original line and column. A second parse
checks for remaining active relative destinations. Literal examples inside code
and comments are exempt.

Strict mode also refuses HTML `srcset`, whose multi-URL syntax is outside this
tool's supported attribute scope. Without strict mode, unresolved destinations
and unsupported attributes remain untouched. Source-mapping errors always fail
instead of guessing which characters to replace.

Strict mode is optional for compatibility, and recommended for generated package
descriptions. A successful check establishes the supported syntax contract; it
does not establish that remote files or anchors exist. Input and output must be
UTF-8 without a byte-order mark or NUL characters.

Exit status is `0` on success, `1` for transformation or file errors, and `2`
for invalid command-line syntax.

## Optional HTML simplification

`-s` / `--simplify` remains opt-in. It follows the shell's two transformations:

1. Convert inline linked Markdown images such as `[![badge](image)](page)` to
   `[badge](page)` throughout active document content.
2. Collapse a `div` with the exact ID `project-readme-header` into one line,
   trimming blank lines and standalone `br` tags.

Other HTML inside the header is retained. Linked HTML screenshot images remain
HTML, including their dimensions. There is no Python-only conversion from HTML
images to Markdown. Code and comments remain protected even when `-s` is
enabled.

Malformed, unclosed, nested or inline header blocks are refused. Headers
containing code blocks, comments or multiline code spans are also refused rather
than collapsed destructively. Keep `-s` off when the publishing platform already
renders the original structure correctly.

## Compatibility and tests

All 21 frozen project READMEs match the shell byte-for-byte with and without
`-s`. The corpus includes conclear, ansible-docsmith, ScanMole and 18 OCI
integration-test repositories. Their source revisions and SHA-256 values are
recorded with the fixtures.

Approved fixes beyond shell behavior are covered by focused fixtures: protected
code/comments; fragment-bearing images and HTML attributes; arbitrary image
extensions; reference definitions; titled links; nested image links; path
normalization; and preservation of HTML formatting, file permissions and line
endings. These cases are intentional corrections, not a general formatting pass.

The [development guide](./DEVELOPMENT.md) describes the fixture suite, shell
comparison, rendering checks, licensing and repeatable `uv` commands. These
checks use temporary files. No project build, release gate, upload or committed
README rewrite is part of this tool's verification.
