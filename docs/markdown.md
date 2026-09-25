# Preparing Markdown for package indexes

`release markdown prepare` rewrites repository-relative Markdown and HTML
destinations to absolute URLs. It preserves the document around those
destinations, including HTML image dimensions. It writes in place, so use it on
a temporary copy or write a separate output file. `release build` prepares the
declared documents inside an exported tree instead, which is what a release
uses.

## Table of contents<a id="toc"></a>

- [Running the command](#running-the-command)
- [Previewing changes](#previewing-changes)
- [Existing in-place usage](#existing-in-place-usage)
- [Branches, tags and source paths](#branches-tags-and-source-paths)
- [Supported transformations](#supported-transformations)
- [Strict validation](#strict-validation)
- [Optional local file checks](#optional-local-file-checks)
- [Optional HTML simplification](#optional-html-simplification)
- [Compatibility and tests](#compatibility-and-tests)

## Running the command<a id="running-the-command"></a>

The command is part of the `releasing` package; see the
[README](../README.md) for installation. Its direct runtime dependencies are
`markdown-it-py` and `typing-extensions`.

```sh
release markdown prepare \
  -o foundata -r example --ref refs/tags/v1.0.0 \
  --strict --output /tmp/example-pypi.md ./README.md
```

Transformation is offline, non-interactive and deterministic for the same
input and arguments. It never invokes Git or consults `.git`.

Write Markdown to stdout instead:

```sh
release markdown prepare \
  -o foundata -r example --ref refs/tags/v1.0.0 \
  --strict --stdout ./README.md
```

`--output -` is equivalent to `--stdout`. Both require one input. Stdout
contains only the transformed Markdown; diagnostics go to stderr. Out-of-place
operation requires explicit organization and repository names, or both custom
URL bases. The output must not alias the input, including through a hard link or
symlink.

## Previewing changes<a id="previewing-changes"></a>

Use `--dry-run` to validate the inputs and show a unified diff without writing
any files:

```sh
release markdown prepare \
  -o foundata -r example --ref refs/tags/v1.0.0 \
  --strict --dry-run ./README.md
```

Diffs and unchanged-file notices go to stderr; stdout stays empty. A successful
preview returns `0`, whether or not changes are needed. Validation errors return
`1`. Every input in a batch is validated before any diff is shown.

Combine `--dry-run` with `--output PATH` to preview a separate output file. The
diff compares the input with the proposed transformation, not with any existing
output file. No output or temporary file is created or replaced. Output alias
and parent-directory checks still apply; a preview does not test write access.
`--stdout` and `--output -` cannot be combined with `--dry-run`.

The displayed diff uses LF line endings and marks missing final newlines. This
does not change the line endings retained in the generated Markdown.

## Existing in-place usage<a id="existing-in-place-usage"></a>

The old positional-file interface remains available, including multiple files:

```sh
release markdown prepare \
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

## Branches, tags and source paths<a id="branches-tags-and-source-paths"></a>

`-b` / `--branch` accepts a branch name. `--ref` accepts `refs/heads/NAME`,
`refs/tags/NAME`, or a full commit SHA. The options are mutually exclusive. Use
an explicit commit SHA when links must identify an exact source revision; tags
remain subject to repository tag-management policy. No ref is resolved or
checked remotely.

For `-b main`, the default bases are:

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
release markdown prepare \
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
release markdown prepare \
  -a https://gitlab.example/org/repo/-/raw/v1.0.0/ \
  -u https://gitlab.example/org/repo/-/blob/v1.0.0/ \
  --strict --output /tmp/example.md ./README.md
```

## Supported transformations<a id="supported-transformations"></a>

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

This is not a Markdown formatter, HTML sanitizer or remote link checker. By
default it does not check file existence; `--repo-root` enables an optional
local check. It never resolves remote refs, fetches URLs or promises to
understand every publishing extension. GFM tables in the corpus are covered by
the independent publishing-renderer tests; arbitrary extensions require their
own fixtures.

## Strict validation<a id="strict-validation"></a>

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

## Optional local file checks<a id="optional-local-file-checks"></a>

`--repo-root DIRECTORY` additionally checks repository-relative destinations
against an explicit local directory. This can be a plain exported tree with no
Git metadata. The input itself may be a temporary file elsewhere:

```sh
release markdown prepare \
  -o foundata -r example --ref refs/tags/v1.0.0 \
  --repo-root /tmp/exported-project --source-path docs/README.md \
  --strict --dry-run /tmp/input-readme.md
```

Resolution uses `--source-path`, not the input's filesystem location. Its
default is still `README.md`, including for each file in a legacy batch. Supply
an explicit source path and process documents individually when their repository
locations differ.

Links may name regular files or directories; images and HTML `src`/`poster`
targets must name regular files. Trailing slashes require directories. Symlinks
are accepted only when they resolve inside the supplied root. Missing targets,
broken or looping symlinks, paths escaping the root and special files fail the
check. URL-encoded paths are decoded once, using the same path resolution as the
rewriter. Queries and fragments are excluded from filesystem lookup.

The check covers supported relative destinations in the original input,
including reference definitions and images that simplification would remove.
Code and comments, external URLs and local `#anchors` are exempt. Remote files,
refs and anchors are not verified; the caller must provide the intended tree.
Unsupported syntax such as `srcset` still requires `--strict` to be rejected.

Local-check errors fail even without `--strict` and include original source
locations. All batch inputs are checked before writing anything. Without
`--repo-root`, transformation does not inspect destination files. The reusable
`releasing.markdown.prepare_markdown()` function remains filesystem-free;
`validate_local_files()` provides the separate optional check.

## Optional HTML simplification<a id="optional-html-simplification"></a>

Two independent flags control simplification:

1. `--simplify-badges` converts inline linked Markdown images such as
   `[![badge](image)](page)` to `[badge](page)` throughout active document
   content. It applies to every such image link, not only badge services.
2. `--collapse-header` collapses a `div` with the exact ID
   `project-readme-header` into one line, trimming blank lines and standalone
   `br` tags. It does not simplify the linked images inside it.

`-s` / `--simplify` remains the compatibility shorthand for both operations,
with badges simplified first. All flags are opt-in; combining `-s` with either
individual flag is harmless. For example, keep a centered header but replace
its linked Markdown badges with text links:

```sh
release markdown prepare \
  -o foundata -r example --simplify-badges --dry-run ./README.md
```

Other HTML inside the header is retained. Linked HTML screenshot images remain
HTML, including their dimensions. There is no Python-only conversion from HTML
images to Markdown. Code and comments remain protected even when `-s` is
enabled.

When header collapse is requested, malformed, unclosed, nested or inline header
blocks are refused. Headers containing code blocks, comments or multiline code
spans are also refused rather than collapsed destructively. Badge-only mode
leaves these headers intact. Leave simplification off when the publishing
platform already renders the original structure correctly.

## Compatibility and tests<a id="compatibility-and-tests"></a>

All 21 frozen project READMEs match their expected output with and without
`-s`. The corpus includes conclear, ansible-docsmith, ScanMole and 18 OCI
integration-test repositories. Their source revisions and SHA-256 values are
recorded with the fixtures.

Approved fixes beyond the original shell behaviour are covered by focused
fixtures: protected code/comments; fragment-bearing images and HTML attributes;
arbitrary image extensions; reference definitions; titled links; nested image
links; path normalization; and preservation of HTML formatting, file permissions
and line endings. These cases are intentional corrections, not a general
formatting pass.

The [development guide](../DEVELOPMENT.md) describes the fixture suite, the
corpus, rendering checks, licensing and repeatable `uv` commands. These
checks use temporary files. Package integration tests also build disposable
sample projects; they do not upload artifacts, run other projects' release
gates or rewrite committed READMEs.
