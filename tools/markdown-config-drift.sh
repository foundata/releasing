#!/usr/bin/env sh
#
# Report every copy of the Markdown style guide's .rumdl.toml that drifted.
#
# The guide owns the rule set and shows it as a `.rumdl.toml` in its "Linting and
# automatic formatting" section. Every repository commits a verbatim copy and
# runs `rumdl` against it, so the copies go stale without a word when the guide
# moves. Four repositories catch that in their own test suite; the collections,
# the skeletons and the drill have no suite to catch it, which is what this
# script is for.
#
# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later

# Boilerplate taken from the foundata shell guide's shell-boilerplate.sh
# (v1.1.2), only the parts this script needs and therefore without its version
# markers.

# Consistent environment for predictable tool and shell behavior
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
set -u                                                      # no uninitialized variables
set -o 2>/dev/null | grep -Fq 'pipefail' && set +o pipefail # older-shell compatibility

# Configure msg() messages (override via environment or inline where needed)
: "${DEBUG:=0}"          # 0: No debug messages. 1: Print debug messages.
: "${MSG_TIMESTAMP:=0}"  # 0: No timestamp (TS) prefix. 1: Unix TS. 2: ISO TS.
: "${MSG_SCRIPTNAME:=0}" # 0: No script name prefix. 1: Enable script name prefix

# Formatting codes (ANSI if STDOUT is TTY and NO_COLOR is empty; empty otherwise)
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  x1b=$(printf '\033') # escape byte (0x1b) (shown as ^[ in most editors)
  # terminfo|termcap comments for reference; alternative for ancient systems:
  # FMT_FOO="$(tput terminfo_foo 2>/dev/null || tput termcap_foo 2>/dev/null)"
  FMT_RESET="${x1b}(B${x1b}[m" # sgr0|me (G0 charset/US-ASCII, attributes reset)
  FMT_BOLD="${x1b}[1m"         # bold|md
  FMT_UL="${x1b}[4m"           # smul|us
  FMT_SO="${x1b}[7m"           # smso|so (standout, reverse video)
  FMT_RED="${x1b}[31m"         # setaf N|AF N (1=red)
  FMT_GREEN="${x1b}[32m"       # setaf N|AF N (2=green)
  FMT_YELLOW="${x1b}[33m"      # setaf N|AF N (3=yellow)
  FMT_BLUE="${x1b}[34m"        # setaf N|AF N (4=blue)
  unset x1b
else
  FMT_RESET='' FMT_BOLD='' FMT_UL='' FMT_SO='' FMT_RED='' FMT_GREEN='' FMT_YELLOW='' FMT_BLUE=''
fi
# shellcheck disable=SC2034 # boilerplate variables, needed but may be unused
readonly FMT_RESET FMT_BOLD FMT_UL FMT_SO FMT_RED FMT_GREEN FMT_YELLOW FMT_BLUE

###
# Print formatted messages to STDOUT or STDERR.
# Options:
#   -e, --error     Print error message (bold red) to STDERR.
#   -w, --warning   Print warning message (bold yellow) to STDERR.
#   -s, --success   Print success message (bold green) to STDOUT.
#   -i, --info      Print info message (bold blue) to STDOUT.
#   -d, --debug     Print debug message (standout) to STDOUT (only if DEBUG=1).
# Globals:
#   DEBUG          - If 0, suppresses -d/--debug messages.
#   MSG_TIMESTAMP  - 1: Enable Unix timestamp as prefix.
#                    2: Enable ISO timestamp as prefix.
#   MSG_SCRIPTNAME - 1: Enable script name as prefix.
# Arguments:
#   $1 - Optional flag (see "Options").
#   $@ - Message to print.
# Outputs:
#   Formatted message to STDOUT or STDERR depending on flag.
msg() {
  local _msg_fd='1' _msg_color='' _msg_prefix='' _msg_fmt=''
  case "${1:-}" in
    '-e' | '--error')
      _msg_fd='2'
      _msg_color="${FMT_BOLD}${FMT_RED}"
      ;;
    '-w' | '--warning')
      _msg_fd='2'
      _msg_color="${FMT_BOLD}${FMT_YELLOW}"
      ;;
    '-s' | '--success')
      _msg_fd='1'
      _msg_color="${FMT_BOLD}${FMT_GREEN}"
      ;;
    '-i' | '--info')
      _msg_fd='1'
      _msg_color="${FMT_BOLD}${FMT_BLUE}"
      ;;
    '-d' | '--dbg' | '--debug')
      [ "${DEBUG:-0}" = 0 ] && return 0
      _msg_fd='1'
      _msg_color="${FMT_SO}"
      ;;
    *) false ;;
  esac && shift
  case "${MSG_TIMESTAMP:-0}" in
    '1') _msg_prefix="[$(date '+%s')] " ;;                  # non-POSIX but widely available: %s
    '2') _msg_prefix="[$(date '+%Y-%m-%dT%H:%M:%S%z')] " ;; # non-POSIX but widely available: %z
    *) ;;
  esac
  case "${MSG_SCRIPTNAME:-0}" in
    '1') _msg_prefix="[${0##*/}] ${_msg_prefix}" ;;
    *) ;;
  esac
  _msg_fmt="${_msg_color}${_msg_prefix}$*${FMT_RESET}"
  [ "${_msg_fd}" = '2' ] && printf '%s\n' "${_msg_fmt}" >&2 || printf '%s\n' "${_msg_fmt}"
}

###
# Check if commands are available.
# Options:
#   -r  Required mode: exit with error if any command is missing.
# Arguments:
#   $@ - Command names to check.
# Returns:
#   0 if all commands exist.
#   1 if any missing (or exit 1 if -r is set)
check_cmd() {
  local required=0
  [ "${1}" = "-r" ] && required=1 && shift
  for cmd; do
    command -v "${cmd}" >/dev/null 2>&1 && continue
    [ "${required}" = 1 ] || return 1
    msg -e "Required command not found: ${cmd}"
    exit 1
  done
}

# Convenience wrapper (see the used function for documentation)
require_cmd() { check_cmd -r "$@"; }

MSG_SCRIPTNAME='1'
script_name="${0##*/}"
guide_file=''
search_directory=''
temporary_directory=''

readonly GUIDE_NAME='markdown-style-guide.md'
readonly CONFIG_NAME='.rumdl.toml'
readonly TEMPLATE_NAME='.rumdl.toml.j2'

###
# Print command usage.
# Globals:
#   script_name
# Outputs:
#   Writes usage information to STDOUT.
usage() {
  printf '%s\n' \
    "Usage: ${script_name} [-g guide] [-t directory]" \
    '' \
    "Compare every committed ${CONFIG_NAME} below a directory of repositories" \
    'with the one the foundata Markdown style guide shows.' \
    '' \
    'Options:' \
    "  -g guide       Path to ${GUIDE_NAME} (default: the copy in" \
    '                 FOUNDATA_GUIDELINES, else guidelines/ below the' \
    '                 searched directory).' \
    '  -t directory   Directory holding the repositories (default: the' \
    '                 directory holding this repository).' \
    '  -h             Print this help.' \
    '' \
    'Exit status:' \
    '  0  Every copy matches the guide.' \
    '  1  A copy drifted, or the guide or the copies could not be read.' \
    '  2  Invalid usage.'
}

###
# Print an error message.
# Arguments:
#   $@ - Error message components.
# Outputs:
#   Writes the error message to STDERR.
print_error() {
  msg -e "$*"
}

###
# Parse command-line options.
# Globals:
#   guide_file       - Updated from -g.
#   search_directory - Updated from -t.
# Arguments:
#   $@ - Command-line arguments.
# Returns:
#   0 on success, 2 on invalid usage.
parse_args() {
  local option

  OPTIND='1'
  while getopts ':g:t:h' option; do
    case "${option}" in
      'g')
        guide_file="${OPTARG}"
        ;;
      't')
        search_directory="${OPTARG}"
        ;;
      'h')
        usage
        exit 0
        ;;
      ':')
        print_error "Option -${OPTARG} requires a value."
        usage >&2
        return 2
        ;;
      '?')
        print_error "Unknown option: -${OPTARG}"
        usage >&2
        return 2
        ;;
      *)
        print_error 'Unable to parse the command-line options.'
        return 2
        ;;
    esac
  done
  shift $((OPTIND - 1))

  if [ "$#" -ne 0 ]; then
    print_error 'Positional arguments are not supported.'
    usage >&2
    return 2
  fi

  return 0
}

###
# The directory holding this repository, where the sibling repositories are.
# Outputs:
#   Writes an absolute directory path to STDOUT.
# Returns:
#   0 on success, 1 when the path cannot be resolved.
default_search_directory() {
  local script_directory="${0%/*}"

  if [ "${script_directory}" = "${0}" ]; then
    script_directory='.'
  fi
  # <directory>/<this repository>/tools/<this script>
  cd "${script_directory}/../.." 2>/dev/null && pwd -P
}

###
# Print the .rumdl.toml the guide's linting section shows.
# Arguments:
#   $1 - Path to the Markdown style guide.
# Outputs:
#   Writes the configuration to STDOUT.
# Returns:
#   0 on success, 1 when the guide shows no such block.
documented_config() {
  awk '
    index($0, "## Linting and automatic formatting") == 1 { section = 1; next }
    section && $0 == "```toml" { inside = 1; next }
    inside && $0 == "```" { closed = 1; exit }
    inside { print }
    END { if (closed != 1) exit 1 }
  ' "${1}"
}

###
# Print every committed copy below a directory, one path per line.
# Arguments:
#   $1 - Directory to search.
# Outputs:
#   Writes sorted paths to STDOUT.
find_copies() {
  find "${1}" -name '.git' -prune -o -type f \
    \( -name "${CONFIG_NAME}" -o -name "${TEMPLATE_NAME}" \) -print \
    | sort
}

###
# Compare every copy with the guide and report each one.
# Globals:
#   guide_file
#   search_directory
#   temporary_directory
# Outputs:
#   Writes one line per copy and a summary to STDOUT, errors to STDERR.
# Returns:
#   0 when every copy matches, 1 otherwise.
run_check() {
  local expected="${temporary_directory}/expected"
  local copies="${temporary_directory}/copies"
  local copy relative state total='0' stale='0'

  if [ ! -f "${guide_file}" ]; then
    print_error "No ${GUIDE_NAME} at: ${guide_file}"
    print_error 'Name it with -g, or point FOUNDATA_GUIDELINES at its directory.'
    return 1
  fi
  if ! documented_config "${guide_file}" >"${expected}"; then
    print_error "No ${CONFIG_NAME} block in the guide's linting section: ${guide_file}"
    return 1
  fi
  if ! find_copies "${search_directory}" >"${copies}"; then
    print_error "Unable to search: ${search_directory}"
    return 1
  fi
  if [ ! -s "${copies}" ]; then
    print_error "No ${CONFIG_NAME} below: ${search_directory}"
    return 1
  fi

  while IFS= read -r copy; do
    total=$((total + 1))
    relative="${copy#"${search_directory}"/}"
    if cmp -s "${copy}" "${expected}"; then
      state='ok'
    else
      state='stale'
      stale=$((stale + 1))
    fi
    printf '%-5s %s\n' "${state}" "${relative}"
  done <"${copies}"

  printf '%s copy/copies checked, %s stale\n' "${total}" "${stale}"
  if [ "${stale}" -ne 0 ]; then
    print_error "Copy the guide's block over the stale file(s) above."
    return 1
  fi

  return 0
}

###
# Main entry point.
# Globals:
#   guide_file
#   search_directory
#   temporary_directory
# Arguments:
#   $@ - Command-line arguments.
main() {
  local parse_status

  require_cmd 'awk' 'cmp' 'find' 'mktemp' 'sort'
  parse_args "$@"
  parse_status="${?}"
  if [ "${parse_status}" -ne 0 ]; then
    exit "${parse_status}"
  fi

  if [ -z "${search_directory}" ] \
    && ! search_directory="$(default_search_directory)"; then
    print_error 'Unable to resolve the directory holding this repository.'
    exit 1
  fi
  if [ ! -d "${search_directory}" ]; then
    print_error "Not a directory: ${search_directory}"
    exit 1
  fi
  if [ -z "${guide_file}" ]; then
    if [ -n "${FOUNDATA_GUIDELINES:-}" ]; then
      guide_file="${FOUNDATA_GUIDELINES}/${GUIDE_NAME}"
    else
      guide_file="${search_directory}/guidelines/${GUIDE_NAME}"
    fi
  fi

  if ! temporary_directory="$(mktemp -d)"; then
    print_error 'Unable to create a temporary directory.'
    exit 1
  fi
  trap 'rm -rf "${temporary_directory}"' EXIT
  trap 'rm -rf "${temporary_directory}"; exit 130' INT
  trap 'rm -rf "${temporary_directory}"; exit 143' TERM

  run_check
}

main "$@"
