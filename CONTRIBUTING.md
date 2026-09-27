# Contributing

Thank you for your interest in contributing. Use these channels:

- Open an issue to report a problem or request a feature.
- Submit code through a pull request (PR) or merge request (MR).
- Send an email to the maintainer if you have something to discuss (no support
  requests).

Development takes place on our internal repository hosting platform. You can
report issues and submit changes through any of our public repositories on
platforms such as GitHub, GitLab or Codeberg. We coordinate the work internally
and follow up on the platform where you contributed.

Report vulnerabilities privately using [`SECURITY.md`](./SECURITY.md).

The [README](./README.md) defines the project's scope: these helpers serve
foundata's release processes, and requests to adapt them to other release
processes are outside that scope.


## Issues<a id="issues"></a>

If you spot a problem, have an idea or want to request a feature, use the issue
tracker where this project's repository is hosted, such as GitHub, GitLab or
Codeberg. Search the existing issues there before opening a new one.

You only need to report an issue once, on one platform. If you know of a related
issue on another platform, include its full URL so we can connect the reports.

We don't assign issues automatically. Leave a comment if you'd like to work on
an issue or have already started. You can also ask us to assign it to you.

Include the `releasing` version, Python version, operating system, command, and
relevant release declaration. Describe the expected result and the error or
incorrect result. Use a minimal example where possible, removing credentials and
private registry or repository details.

State whether the command only performed local checks or reached an external
publication step. This distinction matters when investigating an interrupted
release.


## Discussions<a id="discussions"></a>

If you have something to discuss or comment about the project, feel free to send
an email to Andreas Haerter <ah@foundata.com> (no support requests, all
resources are provided "as is").


## Submitting changes<a id="submitting-changes"></a>

The following requirements apply to both pull requests and merge requests:

Follow the [development guide](./DEVELOPMENT.md) for environment setup, checks,
and the test layout. Add regression coverage for changed behavior and include
the checks you ran in your submission.

Update the relevant command documentation under [`docs/`](./docs/) and record
user-visible changes under `Unreleased` in [`CHANGELOG.md`](./CHANGELOG.md).
Changes to command output, release declarations, or imported library interfaces
can affect consuming projects; describe those effects.

Keep contributions compatible with [`REUSE.toml`](./REUSE.toml), and follow the
[foundata commit guide](https://foundata.com/en/guidelines/git-commits/).
Maintainers follow the [release procedure](./DEVELOPMENT.md#releases) for
publication.

Working on a branch in your own fork lets you make changes without affecting the
original project until we merge them. For help with forks, branches and
submitting changes, use the documentation for the platform hosting the
repository:

| Platform |  Submission type   | Help |
| -------- | ------------------ | ---- |
| GitHub   | Pull request (PR)  | [Quickstart for pull requests](https://docs.github.com/en/pull-requests/get-started/pull-request-quickstart) |
| GitLab   | Merge request (MR) | [Create merge requests](https://docs.gitlab.com/user/project/merge_requests/creating_merge_requests/) |
| Forgejo  | Pull request (PR)  | [Pull requests and Git flow](https://forgejo.org/docs/latest/user/collaboration/pull-requests-and-git-flow/) |
