# Where a release stands

Reports what is true of one version: its changelog entry, its tag locally and
on the remote, what the index serves and whether the forge has a release. It
performs no step and writes nothing.

```sh
release status "${version}" --manifest "../dist-${version}/artifacts.json"
```

```text
ok       changelog          CHANGELOG.md documents 2.0.0
ok       tag                v2.0.0 at 59031c0cb666
unknown  tag pushed         git timed out after 20s
ok       artifact revision  artifacts were built from the tag
ok       index              pypi serves the validated files
ok       forge release      github has a release for v2.0.0
```

## The four states

`ok` is done. `pending` is not done yet, with nothing wrong. `problem` is done
wrongly and needs attention rather than continuation, such as a lightweight
tag, a tag that differs between the remote and this repository, artifacts
built from a commit the tag does not name, or an index serving different bytes
than were validated. `unknown` is a service that could not be reached, which
is neither progress nor breakage.

## Exit status

`0` only when every fact is `ok`, otherwise `1`. Mid-release a non-zero exit
is the normal answer, so a script that only wants the report should append
`|| true`. Whether the release is unfinished or broken is in the report, not
the exit code.

## What it needs

The version, and the release declaration for the repository, tag format and
index. With `--manifest` it also compares the recorded digests against what
the index serves and the recorded revision against the tag, which is the check
that catches artifacts built from the wrong commit.

`--offline` queries neither the remote, the index nor the forge, and reports
those facts as `unknown`. Without it, an unreachable service degrades to
`unknown` on its own rather than failing the report.
