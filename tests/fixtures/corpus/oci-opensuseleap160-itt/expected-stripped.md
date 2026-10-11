# OCI Image: openSUSE Leap 16.0, Integration Test Target (ITT)

[openSUSE Leap 16.0](https://doc.opensuse.org/release-notes/x86_64/openSUSE/Leap/16.0/)
(Linux) for integration testing.

Main features of the [OCI](https://opencontainers.org/) image:

- Fully functional [`systemd`](https://systemd.io/) (not a shim)
- Unprivileged execution support

The image aims to replicate a "VM-like" operating system environment while
maintaining container portability, making it ideal for:

- DevOps validation (like testing Ansible collections, roles, and playbooks)
- CI pipeline testing for quick smoke tests (e.g. before running full VM
  integration test)
- Development environments requiring systemd
- Testing system services and daemons



**⭐ Found this useful? Support open-source and star this project:** [![GitHub repository](https://img.shields.io/github/stars/foundata/oci-opensuseleap160-itt.svg)](https://github.com/foundata/oci-opensuseleap160-itt)

## Table of contents

- [Tags](https://github.com/foundata/oci-opensuseleap160-itt/blob/main/README.md#tags)
- [How to use](https://github.com/foundata/oci-opensuseleap160-itt/blob/main/README.md#usage)
- [Non-goals / Limitations](https://github.com/foundata/oci-opensuseleap160-itt/blob/main/README.md#limitations)
- [Development](https://github.com/foundata/oci-opensuseleap160-itt/blob/main/README.md#development)
- [Contributing](https://github.com/foundata/oci-opensuseleap160-itt/blob/main/README.md#contributing)
- [Licensing, copyright](https://github.com/foundata/oci-opensuseleap160-itt/blob/main/README.md#licensing-copyright)
  - [Container configuration, repository](https://github.com/foundata/oci-opensuseleap160-itt/blob/main/README.md#licensing-copyright-project)
  - [Container image](https://github.com/foundata/oci-opensuseleap160-itt/blob/main/README.md#licensing-copyright-image)
  - [Trademarks](https://github.com/foundata/oci-opensuseleap160-itt/blob/main/README.md#trademarks)
- [Author information](https://github.com/foundata/oci-opensuseleap160-itt/blob/main/README.md#author-information)



## Tags

- `latest`: The most recent release, published for `linux/amd64`.
- `1.0.0`, `1.0.1`, ...: A specific release, following
  [Semantic Versioning](https://semver.org/spec/v2.0.0.html). A version tag
  always names the same image, see [`CHANGELOG.md`](https://github.com/foundata/oci-opensuseleap160-itt/blob/main/CHANGELOG.md) for what
  changed between them.

Use a version tag when a test setup has to stay reproducible and `latest`
when you always want the current image. The image is rebuilt periodically to
include updates and security patches.
`skopeo inspect docker://quay.io/foundata/fedora43-itt:latest` shows when the
current release was built.


## How to use

1. [Install Podman](https://podman.io/docs/installation).
2. Pull the image from
   [Quay](https://quay.io/repository/foundata/opensuseleap160-itt):

   ```bash
   podman pull quay.io/foundata/opensuseleap160-itt:latest
   ```

3. Run a container from the image:

   ```bash
   podman run --detach --name opensuseleap160-itt quay.io/foundata/opensuseleap160-itt:latest
   ```

   Note: **On SELinux-enabled systems**, systemd attempts to write to the cgroup
   filesystem, which might be denied by default security policies. To allow this
   operation, you must **enable the `container_manage_cgroup` boolean** on the
   host system: `sudo setsebool -P container_manage_cgroup 1`
4. Wait until `systemd` has finished booting inside the container:

   ```bash
   until state=$(podman exec opensuseleap160-itt systemctl is-system-running 2>/dev/null); \
     [ "${state}" = running ] || [ "${state}" = degraded ]; do sleep 1; done
   ```

   `running` means every unit started. `degraded` means at least one unit
   failed, list them with `podman exec opensuseleap160-itt systemctl --failed`.
   The loop retries because `systemctl` cannot reach `systemd` in the first
   moment after the container starts.
5. You can now work with the container, e.g. open a Bash terminal:

   ```bash
   podman exec -it opensuseleap160-itt /bin/bash
   ```

   Look around:

   ```bash
   cat /etc/os-release
   systemctl status
   ```



## Non-goals / Limitations

This image is intentionally scoped for integration testing and development
scenarios. It prioritizes compatibility and functionality over security and
performance and is for **usage in isolated environments only**.

Specifically, it does **not** provide:

- Guaranteed compatibility with container runtimes other than
  [Podman](https://podman.io/). We do *not* support
  [Docker](https://www.docker.com/) (but it might work).
- A production-hardened or security-optimized environment (e.g. CIS hardening,
  minimal attack surface).
- Support for long-running, multi-tenant, or internet-facing workloads.
- Optimizations for image size, fast startup time, or minimal resource usage.
- High availability, clustering, or orchestration features (e.g. Kubernetes
  tuning).



## Development

[`DEVELOPMENT.md`](https://github.com/foundata/oci-opensuseleap160-itt/blob/main/DEVELOPMENT.md) describes how to build the image locally,
test it and release a new version. A locally built `:dev` image is for
development only; it is not a release artifact and is not meant to replace the
published image anywhere. [`CHANGELOG.md`](https://github.com/foundata/oci-opensuseleap160-itt/blob/main/CHANGELOG.md) documents what
changed between releases.


## Contributing

See [`CONTRIBUTING.md`](https://github.com/foundata/oci-opensuseleap160-itt/blob/main/CONTRIBUTING.md) for the contribution workflow and
[`DEVELOPMENT.md`](https://github.com/foundata/oci-opensuseleap160-itt/blob/main/DEVELOPMENT.md) for local builds, tests and releases.


## Licensing, copyright

### Container configuration, repository

Copyright (c) 2026, foundata GmbH <https://foundata.com>

This project is licensed under the GNU General Public License v3.0 or later
(SPDX-License-Identifier: `GPL-3.0-or-later`), see
[`LICENSES/GPL-3.0-or-later.txt`](https://github.com/foundata/oci-opensuseleap160-itt/blob/main/LICENSES/GPL-3.0-or-later.txt) for the full
text.

The [`REUSE.toml`](https://github.com/foundata/oci-opensuseleap160-itt/blob/main/REUSE.toml) file provides detailed licensing and copyright
information in a human- and machine-readable format. This includes parts that
may be subject to different licensing or usage terms, such as third-party
components. The repository conforms to the
[REUSE specification](https://reuse.software/spec/). You can use
[`reuse spdx`](https://reuse.readthedocs.io/en/latest/readme.html#cli) to create
an
[SPDX software bill of materials (SBOM)](https://en.wikipedia.org/wiki/Software_Package_Data_Exchange).

[![REUSE status](https://api.reuse.software/badge/github.com/foundata/oci-opensuseleap160-itt)](https://api.reuse.software/info/github.com/foundata/oci-opensuseleap160-itt)



### Container image

An image built from this repository bundles various software components along
with direct and indirect dependencies, which are subject to their respective
licenses. When using it, **you are responsible for ensuring that your usage
complies with all relevant licenses** for the software contained within the
image.

For further licensing information about the software contained in an image built
from this repository, please refer to the following resources:

- <https://en.opensuse.org/openSUSE:License>
- <https://en.opensuse.org/Category:Policies_and_guidelines>



### Trademarks

Third-party trademarks used in this repository:

- Ansible® and Quay® are trademarks of Red Hat, LLC, registered in the United
  States and other countries.
- Docker® is a trademark of Docker, Inc., registered in the European Union and
  the United States.
- Linux® is a trademark of Linus Torvalds, registered in Germany, the European
  Union and the United States.
- openSUSE® is a trademark of SUSE LLC or its affiliates, registered in the
  European Union and the United States.

Their use here is purely descriptive and does not imply any affiliation with or
endorsement by the trademark holders.

Own and licensed trademarks used in this repository:

- foundata® is a trademark of [IPAM GmbH](https://ipam-services.com/),
  registered in Germany and the European Union, licensed to
  [foundata GmbH](https://foundata.com/).


## Author information

This [project](https://foundata.com/en/projects/) was created and is maintained
by [foundata](https://foundata.com/).
