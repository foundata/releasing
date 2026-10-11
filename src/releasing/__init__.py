# SPDX-FileCopyrightText: foundata GmbH <https://foundata.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Release helpers: prepare, check and verify software releases."""

from importlib import metadata

__version__ = metadata.version("releasing")
