# Contributing

Use the [issue tracker](https://github.com/foundata/releasing/issues) to report
problems or propose changes, and submit code through
[pull requests](https://github.com/foundata/releasing/pulls). Report
vulnerabilities privately using [`SECURITY.md`](./SECURITY.md).

The [README](./README.md) defines the project's scope: these helpers serve
foundata's release processes, and requests to adapt them to other release
processes are outside that scope.

## Issues

Include the `releasing` version, Python version, operating system, command, and
relevant release declaration. Describe the expected result and the error or
incorrect result. Use a minimal example where possible, removing credentials and
private registry or repository details.

State whether the command only performed local checks or reached an external
publication step. This distinction matters when investigating an interrupted
release.

## Pull requests

Follow the [development guide](./DEVELOPMENT.md) for environment setup, checks,
and the test layout. Add regression coverage for changed behavior and include
the checks you ran in the pull request.

Update the relevant command documentation under [`docs/`](./docs/) and record
user-visible changes under `Unreleased` in [`CHANGELOG.md`](./CHANGELOG.md).
Changes to command output, release declarations, or imported library interfaces
can affect consuming projects; describe those effects.

Keep contributions compatible with [`REUSE.toml`](./REUSE.toml), and follow the
[foundata commit guide](https://github.com/foundata/guidelines/blob/main/git-commits.md).
Maintainers follow the [release procedure](./DEVELOPMENT.md#releases) for
publication.
