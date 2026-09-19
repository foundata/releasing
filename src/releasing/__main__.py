# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later
"""Allow `python -m releasing` as an alternative to the `release` command."""

from releasing.cli import main

raise SystemExit(main())
