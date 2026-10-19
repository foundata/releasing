# Maintaining requirement identifiers

<!--
SPDX-FileCopyrightText: foundata GmbH <https://foundata.com>
SPDX-License-Identifier: GPL-3.0-or-later
-->

`release markdown requirements` checks, assigns and exports the stable
identifiers in foundata guides. It replaces the guideline repository's
`scripts/check-requirement-identifiers.py`. The commands work on an explicit
UTF-8 Markdown file without a release declaration, Git or network access.

## Table of contents<a id="toc"></a>

- [Running the commands](#running-the-commands)
- [Guide conventions](#guide-conventions)
- [Assigning identifiers](#assigning-identifiers)
- [Inventory compatibility](#inventory-compatibility)
- [Library use](#library-use)

## Running the commands<a id="running-the-commands"></a>

Use a checkout or installed version of `releasing` that includes these commands;
they are newer than 7.0.0. The document path and uppercase ASCII `--prefix` are
required for every operation:

```sh
release markdown requirements check --prefix IG oci-images.md
release markdown requirements assign --prefix IG --dry-run oci-images.md
release markdown requirements assign --prefix IG oci-images.md
release markdown requirements list --prefix IG oci-images.md
release markdown requirements unlabeled --prefix IG oci-images.md
```

Before a package version containing the commands is published, run from the
guide's directory using a sibling checkout of this repository:

```sh
uv run --locked --project ../releasing release markdown requirements check \
  --prefix IG oci-images.md
```

`check` prints the active and retired counts. `list` prints only JSON and
refuses an invalid guide, including one with an unlabeled requirement.
`unlabeled` is a review aid: it prints all items in normative sections that lack
identifiers, including explanations without a normative keyword. It does not
validate the guide; use `check` for that.

Diagnostics and assignment diffs go to stderr. `--quiet` suppresses progress
and diffs, but never errors or result data. Exit codes are `0` for success,
`1` for validation or file errors, and `2` for invalid usage. Only `assign`
accepts `--dry-run`.

## Guide conventions<a id="guide-conventions"></a>

A requirement is a top-level list item with `MUST`, `MUST NOT`, `SHOULD`,
`SHOULD NOT` or `MAY`, or an item in a list immediately following a normative
lead-in such as `**You MUST:**`. An item's own strongest keyword takes
precedence over the lead-in. Every requirement carries this suffix, with a
four-digit number and a matching lowercase anchor:

```markdown
- The release MUST validate its inputs. `IG0001`<a id="ig0001"></a>
```

CommonMark determines list items, paragraphs, headings, fenced and indented
code, inline code and comments. Code, image alternative text and comments do
not supply normative keywords. Requirements in nested lists or quotations,
and normative prose outside top-level list items, are errors. Explanatory
subitems can follow a requirement; they do not become part of its exported
statement.

The Foundata policy excludes the introduction before a level-two heading and
these sections, including their subsections: `Table of contents`, `Goals and
scope`, `Terminology`, `Requirement identifiers`, `Retired requirement
identifiers`, `Reasoning`, and `Author information`. Identifiers on ordinary
items in excluded sections are errors. Retired entries are instead listed
under `Retired requirement identifiers`:

```markdown
- `IG0003`: Replaced by `IG0007` because the obligation changed.
```

Active and retired IDs must use the requested prefix and be unique. An active
ID cannot also be retired. Section names and explicit HTML anchors are kept
in the inventory; the command does not invent section anchors.

## Assigning identifiers<a id="assigning-identifiers"></a>

Assignment appends identifiers above the highest active or retired number.
It keeps existing IDs and never fills gaps. It refuses allocation past 9999.
Only missing identifiers can be repaired automatically; duplicates, malformed
markers, wrong prefixes and other errors must be resolved first.

The complete proposed document is checked before any write. An item ending in
a nested explanation or code block receives an indented final paragraph for
its identifier. Existing source text, line endings and the presence or absence
of a final newline are retained. Changed files are replaced atomically with
their permissions preserved; unchanged files are not replaced. In-place
symlink inputs are refused, including during a dry run.

`--dry-run` shows the proposed diff without changing bytes or file metadata.
Review still decides whether rewording preserves a requirement's meaning or
requires retirement and a new ID. The tool sees the supplied document, not
historical revisions: removing both an ID and its retirement record cannot be
detected from that document alone.

## Inventory compatibility<a id="inventory-compatibility"></a>

The export retains the old script's object structure:

```json
{
  "guide": "oci-images.md",
  "requirements": [
    {
      "id": "IG0001",
      "modality": "MUST",
      "section": "Release workflow",
      "anchor": "release-workflow",
      "line": 240,
      "text": "The release MUST validate its inputs."
    }
  ],
  "retired": [{"id": "IG0003", "note": "`IG0003`: Replaced by `IG0007`."}]
}
```

Requirements remain in document order; line numbers are one-based. Text is
Markdown flattened to one line, without the identifier suffix. Retirement
notes now include continuation lines, which the old script dropped. Unlike the
old `--list`, invalid guides produce no JSON and exit with `1`.

ConClear can keep its existing importer. Its guide revision, coverage mappings
and retirement decisions remain owned by ConClear and the guide's maintainers.

## Library use<a id="library-use"></a>

`releasing.requirements` provides `parse(source)`, `check(guide, prefix=...)`,
`assign(guide, prefix=...)` and `listing(guide, prefix=..., name=...)`.
`check` returns source-located diagnostics; `assign` returns the proposed text;
`listing` returns the inventory dictionary. Assignment and export raise
`ValueError` on invalid input. These functions perform no filesystem access
and print nothing. Their caller owns file reading, writing and reporting.
