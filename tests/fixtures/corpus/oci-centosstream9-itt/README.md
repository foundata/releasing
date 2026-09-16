# OCI Image: CentOS Stream 9, Integration Test Target (ITT)

[CentOS Stream 9](https://www.centos.org/stream9/) (Linux) for integration
testing.

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



<!-- rumdl-disable MD033 -->
<!-- HTML for consistent rendering across limited platform parsers -->
<div align="center" id="project-readme-header">
<br>
<br>

**⭐ Found this useful? Support open-source and star this project:**

[![GitHub repository](https://img.shields.io/github/stars/foundata/oci-centosstream9-itt.svg)](https://github.com/foundata/oci-centosstream9-itt)

<br>
</div>
<!-- rumdl-enable MD033 -->

## Table of contents<a id="toc"></a>

- [Tags](#tags)
- [How to use](#usage)
- [Non-goals / Limitations](#limitations)
- [Development](#development)
- [Contributing](#contributing)
- [Licensing, copyright](#licensing-copyright)
  - [Container configuration, repository](#licensing-copyright-project)
  - [Container image](#licensing-copyright-image)
  - [Trademarks](#trademarks)
- [Author information](#author-information)



## Tags<a id="tags"></a>

- `latest`: The most recent release, published for `linux/amd64`.
- `1.0.0`, `1.0.1`, ...: A specific release, following
  [Semantic Versioning](https://semver.org/spec/v2.0.0.html). A version tag
  always names the same image, see [`CHANGELOG.md`](CHANGELOG.md) for what
  changed between them.

Use a version tag when a test setup has to stay reproducible and `latest`
when you always want the current image. The image is rebuilt periodically to
include updates and security patches.
`skopeo inspect docker://quay.io/foundata/fedora43-itt:latest` shows when the
current release was built.


## How to use<a id="usage"></a>

1. [Install Podman](https://podman.io/docs/installation).
2. Pull the image from
   [Quay](https://quay.io/repository/foundata/centosstream9-itt):

   ```bash
   podman pull quay.io/foundata/centosstream9-itt:latest
   ```

3. Run a container from the image:

   ```bash
   podman run --detach --name centosstream9-itt quay.io/foundata/centosstream9-itt:latest
   ```

   Note: **On SELinux-enabled systems**, systemd attempts to write to the cgroup
   filesystem, which might be denied by default security policies. To allow this
   operation, you must **enable the `container_manage_cgroup` boolean** on the
   host system: `sudo setsebool -P container_manage_cgroup 1`
4. Wait until `systemd` has finished booting inside the container:

   ```bash
   until state=$(podman exec centosstream9-itt systemctl is-system-running 2>/dev/null); \
     [ "${state}" = running ] || [ "${state}" = degraded ]; do sleep 1; done
   ```

   `running` means every unit started. `degraded` means at least one unit
   failed, list them with `podman exec centosstream9-itt systemctl --failed`.
   The loop retries because `systemctl` cannot reach `systemd` in the first
   moment after the container starts.
5. You can now work with the container, e.g. open a Bash terminal:

   ```bash
   podman exec -it centosstream9-itt /bin/bash
   ```

   Look around:

   ```bash
   cat /etc/os-release
   systemctl status
   ```



## Non-goals / Limitations<a id="limitations"></a>

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



## Development<a id="development"></a>

[`DEVELOPMENT.md`](DEVELOPMENT.md) describes how to build the image locally,
test it and release a new version. A locally built `:dev` image is for
development only; it is not a release artifact and is not meant to replace the
published image anywhere. [`CHANGELOG.md`](CHANGELOG.md) documents what
changed between releases.


## Contributing<a id="contributing"></a>

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the contribution workflow and
[`DEVELOPMENT.md`](DEVELOPMENT.md) for local builds, tests and releases.


## Licensing, copyright<a id="licensing-copyright"></a>

### Container configuration, repository<a id="licensing-copyright-project"></a>

<!--REUSE-IgnoreStart-->
<!-- rumdl-disable-next-line MD034 --><!-- should match SPDX-PackageSupplier -->
Copyright (c) 2025, 2026 foundata GmbH (https://foundata.com)

This project is licensed under the GNU General Public License v3.0 or later
(SPDX-License-Identifier: `GPL-3.0-or-later`), see
[`LICENSES/GPL-3.0-or-later.txt`](LICENSES/GPL-3.0-or-later.txt) for the full
text.

The [`REUSE.toml`](REUSE.toml) file provides detailed licensing and copyright
information in a human- and machine-readable format. This includes parts that
may be subject to different licensing or usage terms, such as third-party
components. The repository conforms to the
[REUSE specification](https://reuse.software/spec/). You can use
[`reuse spdx`](https://reuse.readthedocs.io/en/latest/readme.html#cli) to create
a
[SPDX software bill of materials (SBOM)](https://en.wikipedia.org/wiki/Software_Package_Data_Exchange).
<!--REUSE-IgnoreEnd-->

[![REUSE status](https://api.reuse.software/badge/github.com/foundata/oci-centosstream9-itt)](https://api.reuse.software/info/github.com/foundata/oci-centosstream9-itt)



### Container image<a id="licensing-copyright-image"></a>

An image built from this repository bundles various software components along
with direct and indirect dependencies, which are subject to their respective
licenses. When using it, **you are responsible for ensuring that your usage
complies with all relevant licenses** for the software contained within the
image.

For further licensing information about the software contained in an image built
from this repository, please refer to the following resources:

- <https://www.centos.org/legal/licensing-policy/>



### Trademarks<a id="trademarks"></a>

- Red Hat®, CentOS®, Ansible® and Quay® are trademarks of Red Hat, Inc.,
  registered in the US and other countries
- Docker® is a trademark of Docker, Inc.
- Linux® is a registered trademark of Linus Torvalds

Their use here is purely descriptive and does not imply any affiliation with or
endorsement by the trademark holders.


## Author information<a id="author-information"></a>

This [project](https://foundata.com/en/projects/) was created and is maintained
by [foundata](https://foundata.com/).
