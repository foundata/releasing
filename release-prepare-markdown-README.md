# release-prepare-markdown.sh - Usage Examples

## Overview

This script converts relative links in markdown files to absolute URLs, making them work correctly on package hosting platforms like PyPI, npm, etc.

## Features

- ✅ Converts markdown links: `[text](./path)` → absolute URL
- ✅ Converts markdown images: `![alt](./image.png)` → raw URL
- ✅ Converts HTML href attributes: `href="./path"`
- ✅ Converts HTML src attributes: `src="./image.png"`
- ✅ Handles paths with and without `./` prefix
- ✅ Supports subdirectory paths: `docs/guide.md`
- ✅ Preserves external links, absolute paths, and anchors
- ✅ Uses raw URLs for images/binary files
- ✅ Uses UI URLs for documentation files
- ✅ Shows unified diff before replacing files
- ✅ Reports when no changes are needed

## Basic Usage

```bash
# Process a single README.md file with auto-detected settings
./release-prepare-markdown.sh README.md

# Process multiple files
./release-prepare-markdown.sh README.md CHANGELOG.md docs/*.md
```

## Auto-Detected Defaults

When run from `/home/user/dev/foundata/ansible-docsmith/`:

- **Organization**: `foundata` (parent directory name)
- **Repository**: `ansible-docsmith` (current directory name)
- **Branch**: `main`
- **Raw URL base**: `https://raw.githubusercontent.com/foundata/ansible-docsmith/refs/heads/main/`
- **UI URL base**: `https://github.com/foundata/ansible-docsmith/blob/main/`

## Custom Options

```bash
# Specify custom branch
./release-prepare-markdown.sh -b develop README.md

# Override organization and repository
./release-prepare-markdown.sh -o myorg -r myrepo README.md

# Use custom URL bases (e.g., for GitLab)
./release-prepare-markdown.sh \
    -u "https://gitlab.com/myorg/myrepo/-/blob/main/" \
    -a "https://gitlab.com/myorg/myrepo/-/raw/main/" \
    README.md
```

## Conversion Examples

### Before Processing

```markdown
# My Project

See the [REUSE.toml](./REUSE.toml) file for licensing.

Read the [contributing guide](docs/CONTRIBUTING.md).

![Logo](./logo.png)

![Screenshot](assets/screenshot.jpg)

<img src="./banner.png" alt="Banner">
```

### Script Output with Diff

```bash
$ ./release-prepare-markdown.sh README.md

Processing: README.md

Changes for README.md:
----------------------------------------
--- README.md
+++ README.md
@@ -1,11 +1,11 @@
 # My Project
 
-See the [REUSE.toml](./REUSE.toml) file for licensing.
+See the [REUSE.toml](https://github.com/foundata/ansible-docsmith/blob/main/REUSE.toml) file for licensing.
 
-Read the [contributing guide](docs/CONTRIBUTING.md).
+Read the [contributing guide](https://github.com/foundata/ansible-docsmith/blob/main/docs/CONTRIBUTING.md).
 
-![Logo](./logo.png)
+![Logo](https://raw.githubusercontent.com/foundata/ansible-docsmith/refs/heads/main/logo.png)
 
-![Screenshot](assets/screenshot.jpg)
+![Screenshot](https://raw.githubusercontent.com/foundata/ansible-docsmith/refs/heads/main/assets/screenshot.jpg)
 
-<img src="./banner.png" alt="Banner">
+<img src="https://raw.githubusercontent.com/foundata/ansible-docsmith/refs/heads/main/banner.png" alt="Banner">
----------------------------------------

Completed: README.md
All files processed successfully
```

### After Processing

```markdown
# My Project

See the [REUSE.toml](https://github.com/foundata/ansible-docsmith/blob/main/REUSE.toml) file for licensing.

Read the [contributing guide](https://github.com/foundata/ansible-docsmith/blob/main/docs/CONTRIBUTING.md).

![Logo](https://raw.githubusercontent.com/foundata/ansible-docsmith/refs/heads/main/logo.png)

![Screenshot](https://raw.githubusercontent.com/foundata/ansible-docsmith/refs/heads/main/assets/screenshot.jpg)

<img src="https://raw.githubusercontent.com/foundata/ansible-docsmith/refs/heads/main/banner.png" alt="Banner">
```

## What Gets Converted

### ✅ Converted to Absolute URLs

- `[text](./path)` - links with ./ prefix
- `[text](path)` - relative links starting with alphanumeric
- `[text](docs/guide.md)` - subdirectory paths
- `href="./path"` and `href="path"` - HTML links
- `![img](./pic.png)` - images with ./ prefix
- `![img](assets/pic.png)` - relative image paths
- `src="./image.png"` - HTML image sources

### ❌ NOT Converted (Preserved)

- `[Google](https://google.com)` - external links (contain ://)
- `[Root](/root/file.md)` - absolute paths (start with /)
- `[Section](#anchor)` - anchor links (start with #)
- `[Already](https://github.com/org/repo/file.md)` - already absolute

## Image/Binary File Extensions

These file types use the raw URL base:
- Images: png, jpg, jpeg, svg, gif, webp, ico
- Archives: zip, tar, gz, bz2, xz
- Media: mp4, webm
- Documents: pdf

All other files use the UI URL base for proper rendering on GitHub.

## Integration with CI/CD

```yaml
# Example GitHub Actions workflow
- name: Prepare README for release
  run: |
    ./release-prepare-markdown.sh README.md
    
# The modified README.md can now be packaged
```

## Requirements

- Bash 4.0+
- sed with extended regex support (-E flag)
- Standard Unix utilities (basename, dirname, mktemp)

## Coding Standards

The script follows these standards:
- ✅ Shellcheck validated
- ✅ Formatted with shfmt (--indent 4 --posix)
- ✅ Uses `${var}` notation throughout
- ✅ No color output
- ✅ Proper error handling with set -e -u

## Notes

- The script modifies files in-place
- A unified diff is displayed before each file is modified
- Files with no changes show "No changes needed" message
- Original files are replaced with processed versions
- Make sure to backup or version control your files before running
- The script uses temporary files during processing for safety
