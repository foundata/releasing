# The Quay repository description

<!--
SPDX-FileCopyrightText: foundata GmbH <https://foundata.com>
SPDX-License-Identifier: GPL-3.0-or-later
-->

```sh
release quay description-set --ref "refs/tags/v${version}" \
  -o foundata -r oci-example \
  --token-file ~/.config/conclear/quay.token \
  quay.io/foundata/example
```

The command publishes a repository's `README.md` as the description of one or
more Quay repositories. It reads the document from `--ref`, a qualified tag or
branch ref or a full commit SHA, never from the working tree. The links in the
description point at the same ref on the forge, so the description and its links
name the same source. `-o` and `-r` name the forge repository; `-a` and `-u`
replace both URL bases for another forge, as in
[`markdown prepare`](./markdown.md#branches-tags-and-source-paths).
`--source-path` selects another document.

The command needs no release declaration. It works on its own: before a
project's first release, while adopting the tooling, or to bring a description
back in line. Run as a release step, it comes after the image is published and
names the tag that `latest` now points to, so Quay never describes a version
it does not serve.

## Table of contents<a id="toc"></a>

- [What Quay gets](#what-quay-gets)
- [Checks before and after the write](#checks)
- [The token](#the-token)
- [Previewing](#previewing)
- [Refusals](#refusals)

## What Quay gets<a id="what-quay-gets"></a>

Quay renders the description as Markdown in two web interfaces. The newer one
shows raw HTML as literal text, so comments, heading anchors and `<br>` appear
as written. The older one, which quay.io still serves unless a visitor
switches, drops raw HTML instead. Neither gives headings IDs, so in-page links
lead nowhere in both. The document is prepared the way
`release markdown prepare --collapse-header --strip-html --absolute-anchors
--strict` prepares it, and reads the same in both interfaces:

- Repository-relative links and images become absolute URLs at the ref.
- The `project-readme-header` block becomes one line.
- HTML comments, empty heading anchors and `<br>` are removed; see
  [HTML stripping](./markdown.md#optional-html-stripping). Any other raw HTML,
  such as an HTML screenshot, is refused rather than shown as text.
- In-page links such as `[Usage](#usage)` point at the same anchor in the
  document on the forge, because the description has none; see
  [absolute anchors](./markdown.md#optional-absolute-anchors).

The same form can be inspected without any request by running
`release markdown prepare` with those switches.

## Checks before and after the write<a id="checks"></a>

The revision is exported as `release build` exports it, and every relative link
and image is checked against that export, so a description cannot link to a
file the tag does not have.

Each repository's current description is read first. A repository that already
shows the prepared description is left alone. After a write, the description
Quay stores is read back and must equal what was sent. When a write gets no
answer, the read decides whether it arrived. Nothing is retried. On success, the
page of each repository is printed on standard output.

## The token<a id="the-token"></a>

Quay has no command-line tool that holds a login, so the write needs an API
token: an OAuth application token with the `repo:write` scope, whose user has
write permission on the repositories. Quay issues such tokens through an OAuth
application of the organization; a robot account's token is not accepted by
the API. Quay creates the token on behalf of the user who generates it, and
within its scopes it reaches every repository that user can reach.

A release host that runs [ConClear](https://foundata.com/en/projects/conclear/)
already has such a token: its release profile names it as `token_file`, and
tag writes need the same scope. Pass that file to `--token-file`.

The token is read from the file and nowhere else, never from an argument or an
environment variable. The file must be a regular file, not a symbolic link,
and outside Windows it must belong to you and grant nothing to group or others
(`chmod 600`). The token is sent only in the `Authorization` header to the API
URL, which must use HTTPS. It is never printed. `--api-url` names another Quay
installation; each repository's host must be the one that API serves.

## Previewing<a id="previewing"></a>

`--dry-run` reads the current descriptions and shows the difference to the
prepared one on standard error. It writes nothing and prints nothing on
standard output. Without `--token-file` it reads anonymously, which works for
public repositories.

```sh
release quay description-set --ref "refs/tags/v${version}" \
  -o foundata -r oci-example --dry-run quay.io/foundata/example
```

## Refusals<a id="refusals"></a>

The command refuses before any request when the ref does not resolve, the
document is missing at the ref, a relative link names a file the ref does not
have, the document contains raw HTML that stripping does not remove, or a
repository is not named as `HOST/NAMESPACE/NAME` of the API's host.

Quay's own refusals name what it needs: HTTP 401 for a token Quay does not
accept, 403 for a missing scope or permission, 404 for a repository that does
not exist or that the token's user cannot see. quay.io checks the description
of a repository without tags for spam and may refuse it with HTTP 400; a
repository that holds a tagged image is not checked.
