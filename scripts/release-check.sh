#!/usr/bin/env bash
# Bash required for: arrays (the version matrix) and BASH_SOURCE.
#
# Local, provider-independent release check for releasing.
#
# Runs the full quality gate (format, lint, strict type check, Markdown, shell
# checks, tests) on every supported Python version, then builds the wheel and
# source distribution with `release build`, installs the wheel into a clean
# throwaway environment and smoke-tests the installed artifact.
#
# This is intended to be run before tagging a release. It does not depend on any
# CI service; CI (if added) should call the same steps.
#
# This package releases itself: the `release` commands of a release run this
# working tree's own code. That argument only holds if these checks actually
# ran, which is what this script is for.
#
# Usage:
#   scripts/release-check.sh [PYTHON_VERSION ...]
#
# Without arguments the supported version matrix below is used.
#
# The artifacts are built by `release build`, which exports the committed
# revision, prepares the README that ships in them, refuses developer litter
# inside them and records their digests. Building with it here means the gate
# smoke-tests what a release uploads. See DEVELOPMENT.md.

# Consistent environment for predictable tool and shell behavior.
export PATH="${PATH:-/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin}"
if command -v locale >/dev/null 2>&1; then
  for locale_candidate in 'C.UTF-8' 'C.utf8' 'en_US.UTF-8' 'UTF-8' 'C'; do
    if LC_ALL="${locale_candidate}" locale charmap >/dev/null 2>&1; then
      export LC_ALL="${locale_candidate}"
      break
    fi
  done
else
  export LC_ALL='C'
fi
readonly LC_ALL
unset locale_candidate

# Against the style guide's default, and deliberately: this is a gate where any
# single failure must stop the release, so an abort-by-default is worth more
# here than the edge cases set -e is rightly criticised for. The three options
# below close the ones that would otherwise let a failure through.
set -e
set -u
set -o pipefail
shopt -s inherit_errexit

# Temp environments live under ${TMPDIR}, often on a different filesystem than
# the uv cache; copy instead of hardlink to avoid a noisy fallback warning.
export UV_LINK_MODE='copy'

# Supported Python versions (keep in sync with pyproject's requires-python and
# DEVELOPMENT.md). Arguments override them; main() parses that.
supported_pythons=('3.11' '3.12' '3.13' '3.14')

# Resolve the package directory (this script lives in <pkg>/scripts/).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR
PKG_DIR="$(dirname "${SCRIPT_DIR}")"
readonly PKG_DIR
cd "${PKG_DIR}"

# Every shell script this repository ships, by dialect, with the option sets the
# shell style guide prescribes for each tool.
readonly -a POSIX_SCRIPTS=(
  'tools/git-review-unpushed.sh'
  'tools/markdown-config-drift.sh'
)
readonly -a BASH_SCRIPTS=(
  'scripts/release-check.sh'
)
readonly -a SHFMT_OPTS_COMMON=(
  '--indent' '2' '--case-indent' '--binary-next-line' '--simplify'
)
readonly -a SHELLCHECK_OPTS_COMMON=(
  '--severity=style' '--exclude=SC2292' '--exclude=SC3040'
  '--exclude=SC3043' '--enable=all'
)

# Expected distribution, import and command names.
readonly DIST_NAME='releasing'
readonly IMPORT_NAME='releasing'
readonly COMMAND_NAME='release'

WORK_DIR="$(mktemp -d)"
readonly WORK_DIR
readonly DIST_DIR="${WORK_DIR}/dist"
trap 'rm -rf "${WORK_DIR}"' EXIT

###
# Announce the step that follows.
# Arguments:
#   $@ - The step description.
# Outputs:
#   Writes a blank-line-separated banner to STDOUT.
log() { printf '\n=== %s ===\n' "$*"; }

###
# Abort unless every named tool is available.
# Arguments:
#   $@ - The commands this gate is about to drive.
# Outputs:
#   Writes an error naming the first missing tool to STDERR.
# Returns:
#   0 when all are present, exits 1 otherwise.
require_tools() {
  local command_name
  for command_name in "$@"; do
    if ! command -v "${command_name}" >/dev/null 2>&1; then
      printf "error: '%s' is required but not found in PATH\n" "${command_name}" >&2
      exit 1
    fi
  done
}

###
# Refuse a release whose tracked content differs from HEAD. Everything below
# builds and validates HEAD, so uncommitted work would be validated without
# being what ships.
# Returns:
#   0 when the tracked tree is clean, exits 1 otherwise.
check_clean_tree() {
  log "Clean checkout"
  local tracked
  tracked="$(git status --porcelain --untracked-files=no)"
  if [ -n "${tracked}" ]; then
    printf 'error: tracked files differ from HEAD; commit or stash first\n' >&2
    printf '%s\n' "${tracked}" >&2
    exit 1
  fi
  git diff --check
}

###
# Check every shipped shell script with the tools and the exact options the
# shell style guide prescribes, so the style holds without anyone remembering
# to run them. The dialect parse is part of it: a script can lint clean and
# still not parse under the shell in its shebang.
# Globals:
#   BASH_SCRIPTS, POSIX_SCRIPTS, SHELLCHECK_OPTS_COMMON, SHFMT_OPTS_COMMON
# Returns:
#   0 when every script passes, non-zero otherwise.
check_shell_scripts() {
  log "Shell scripts (shfmt, shellcheck, checkbashisms, syntax)"
  local script
  for script in "${POSIX_SCRIPTS[@]}"; do
    shfmt --language-dialect posix "${SHFMT_OPTS_COMMON[@]}" --diff "${script}"
    shellcheck --shell=sh "${SHELLCHECK_OPTS_COMMON[@]}" "${script}"
    checkbashisms "${script}"
    sh -n "${script}"
  done
  for script in "${BASH_SCRIPTS[@]}"; do
    shfmt --language-dialect bash "${SHFMT_OPTS_COMMON[@]}" --diff "${script}"
    shellcheck --shell=bash "${SHELLCHECK_OPTS_COMMON[@]}" "${script}"
    bash -n "${script}"
  done
}

###
# Make sure every supported interpreter is available so the matrix can actually
# run. `uv python install` is idempotent and a no-op when the version is
# already present.
# Globals:
#   supported_pythons
ensure_pythons() {
  log "Ensure Python interpreters: ${supported_pythons[*]}"
  uv python install "${supported_pythons[@]}"
}

###
# Assert the declarations agree with each other before anything is built. Every
# uv call in this gate passes --locked, so the first of them refuses a lockfile
# that no longer matches pyproject.
run_declaration_checks() {
  log "Declarations (lockfile, release config, version, changelog)"
  uv run --locked release config check
  uv run --locked release version check
  uv run --locked release changelog check
}

###
# Run the formatter, linter, type checker and Markdown gate once. They are
# version-independent here, because mypy targets the project minimum via
# pyproject.
run_static_checks() {
  log "Static checks (format, lint, type check, Markdown)"
  uv run --locked ruff format --check .
  uv run --locked ruff check .
  uv run --locked mypy
  uv run --locked python tests/check_markdown.py
}

###
# Run the test suite on every supported interpreter.
# Globals:
#   supported_pythons
run_tests_matrix() {
  local py
  for py in "${supported_pythons[@]}"; do
    log "Tests on Python ${py}"
    uv run --locked --python "${py}" --isolated pytest -q
  done
}

###
# Build the wheel and source distribution with `release build`: it exports the
# committed revision, so the developer tree's ignored litter (tool caches,
# editor droppings) never decides what ships, and it refuses an artifact that
# carries caches or bytecode.
# Globals:
#   DIST_DIR
build_artifacts() {
  log "Build wheel and source distribution (release build)"
  uv run --locked release build --out "${DIST_DIR}"
  ls -1 "${DIST_DIR}"
}

###
# Install the built wheel into a clean environment per supported interpreter
# and smoke-test the installed artifact, never the sources. The command must
# report the version pyproject declares, so a wheel built from stale metadata
# is caught here rather than after the upload.
# Globals:
#   COMMAND_NAME, DIST_DIR, IMPORT_NAME, supported_pythons, WORK_DIR
# Returns:
#   0 when every interpreter passes, exits 1 otherwise.
smoke_test_matrix() {
  # An unmatched glob stays literal, so the -f test below is what decides.
  local wheel
  wheel="$(printf '%s\n' "${DIST_DIR}"/*.whl | head -n 1)"
  if [ ! -f "${wheel}" ]; then
    printf 'error: no wheel in %s\n' "${DIST_DIR}" >&2
    exit 1
  fi
  local declared
  declared="$(uv run --locked python -c '
import tomllib
with open("pyproject.toml", "rb") as handle:
    print(tomllib.load(handle)["project"]["version"])
')"
  local py env_dir
  for py in "${supported_pythons[@]}"; do
    log "Smoke test the installed wheel on Python ${py}"
    env_dir="${WORK_DIR}/smoke-${py}"
    uv venv --quiet --python "${py}" "${env_dir}"
    uv pip install --quiet --python "${env_dir}/bin/python" "${wheel}"
    # __version__ reads the installed distribution metadata, so this compares
    # what the wheel carries against what pyproject declares.
    local reported
    reported="$("${env_dir}/bin/python" -c "import ${IMPORT_NAME}; print(${IMPORT_NAME}.__version__)")"
    printf '%s reports: %s\n' "${IMPORT_NAME}" "${reported}"
    if [ "${reported}" != "${declared}" ]; then
      printf 'error: installed %s reports %s, pyproject declares %s\n' \
        "${IMPORT_NAME}" "${reported}" "${declared}" >&2
      exit 1
    fi
    # The entry point must run from the installed artifact; this CLI requires a
    # command, so --help is the argument-free surface that proves it works.
    "${env_dir}/bin/${COMMAND_NAME}" --help >/dev/null
    "${env_dir}/bin/${COMMAND_NAME}" config --help >/dev/null
  done
}

###
# Drive the gate.
# Arguments:
#   $@ - Optional Python versions replacing the supported matrix.
main() {
  if [ "$#" -gt 0 ]; then
    supported_pythons=("$@")
  fi

  require_tools 'uv' 'git' 'shellcheck' 'shfmt' 'checkbashisms'
  printf 'Release check for %s\n' "${DIST_NAME}"
  printf 'Python versions: %s\n' "${supported_pythons[*]}"
  check_clean_tree
  ensure_pythons
  run_declaration_checks
  run_static_checks
  check_shell_scripts
  run_tests_matrix
  build_artifacts
  smoke_test_matrix
  log "All release checks passed"
}

main "$@"
