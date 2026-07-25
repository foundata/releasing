#!/usr/bin/env sh
#
# Review and optionally edit unpushed commit messages from oldest to newest.
#
# SPDX-FileCopyrightText: 2026, foundata GmbH (https://foundata.com)
# SPDX-License-Identifier: GPL-3.0-or-later

# --- BOILERPLATE START v1.1.1 ---
# Consistent environment for predictable tool and shell behavior
export PATH="${PATH:-'/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin'}"
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
set -o 2>/dev/null | grep -Fq 'pipefail' && set +o pipefail # disable pipefail as it's non-POSIX

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
# Manage cleanup commands on exit/interrupt (LIFO order).
# Globals:
#   _TRAP_STACK - Newline-separated list of commands (newest first).
#                 Modified by push/pop/run operations.
# Arguments:
#   $1      - Action: push (add to stack), pop (remove last (no execute)),
#             or run (execute all & clear).
#   $2      - Command to register (required for push).
# Returns:
#   0 on success, 1 on invalid usage.
# Example:
#   trap_stack push 'rm -rf "/tmp/mydir"'
#   trap_stack pop
#   trap_stack run
_TRAP_STACK=''
trap_stack() {
  case "${1:-}" in
    'push')
      # line break is needed (stack delimiter)
      _TRAP_STACK="${2:?Command required}${_TRAP_STACK:+
${_TRAP_STACK}}"
      trap 'trap_stack run' EXIT
      trap 'trap_stack run; exit 130' INT
      trap 'trap_stack run; exit 143' TERM
      ;;
    'pop')
      _TRAP_STACK="$(printf '%s\n' "${_TRAP_STACK}" | tail -n +2)"
      [ -z "${_TRAP_STACK}" ] && trap - EXIT INT TERM
      ;;
    'run')
      while [ -n "${_TRAP_STACK}" ]; do
        eval "$(printf '%s\n' "${_TRAP_STACK}" | head -n 1)" || true
        _TRAP_STACK="$(printf '%s\n' "${_TRAP_STACK}" | tail -n +2)"
      done
      trap - EXIT INT TERM
      ;;
    *)
      printf 'Usage: trap_stack push|pop|run [cmd]\n' >&2
      return 1
      ;;
  esac
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

###
# Run a command that should never fail. If the command fails, print an error
# and exit immediately.
# Arguments:
#   $@ - Command and arguments to execute.
# Outputs:
#   Error message to STDERR on failure.
# Returns:
#   0 on success.
#   >0 (the original exit code of the command) on failure.
ensure() {
  local exit_code
  "$@"
  exit_code="$?"
  if [ "${exit_code}" -ne 0 ]; then
    msg -e "Command failed (exit code ${exit_code}): $*"
    exit "${exit_code}"
  fi
  return 0
}

# Convenience wrappers (see the used functions for documentation)
require_cmd() { check_cmd -r "$@"; }
# --- BOILERPLATE END v1.1.1 ---

MSG_SCRIPTNAME='1'
script_name="${0##*/}"
target_directory='.'
upstream=''
repository=''
git_directory=''
rebase_started='0'
review_index='0'
review_total='0'

###
# Print command usage.
# Outputs:
#   Writes usage information to STDOUT.
usage() {
  printf '%s\n' \
    "Usage: ${script_name} [-t repository] [-u upstream]" \
    '' \
    'Review unpushed commit messages from oldest to newest.' \
    '' \
    'Options:' \
    '  -t repository  Local Git repository (default: current directory).' \
    '  -u upstream    Comparison ref (default: current branch upstream).' \
    '  -h             Print this help.' \
    '' \
    'Actions for each commit:' \
    '  e  Edit the commit message, then review the same commit again.' \
    '  d  Show the diff against the commit parent, then return.' \
    '  n  Accept the message and continue to the next commit.' \
    '  a  Abort and restore the original branch.'
}

###
# Print an error message.
# Globals:
#   script_name
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
#   target_directory - Updated from -t.
#   upstream         - Updated from -u.
# Arguments:
#   $@ - Command-line arguments.
# Returns:
#   0 on success, 2 on invalid usage.
parse_args() {
  local option

  OPTIND='1'
  while getopts ':t:u:h' option; do
    case "${option}" in
      't')
        target_directory="${OPTARG}"
        ;;
      'u')
        upstream="${OPTARG}"
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
# Replace each generated rebase "pick" command with "edit".
# Arguments:
#   $1 - Path to the interactive-rebase todo file.
# Returns:
#   0 on success, 1 on failure.
prepare_rebase_todo() {
  local todo_file="${1}"
  local temporary_file="${todo_file}.git-review-unpushed.$$"

  if ! sed 's/^pick /edit /' "${todo_file}" >"${temporary_file}"; then
    rm -f "${temporary_file}"
    return 1
  fi
  if ! mv "${temporary_file}" "${todo_file}"; then
    rm -f "${temporary_file}"
    return 1
  fi

  return 0
}

###
# Resolve the script path so Git can invoke its internal todo editor.
# Globals:
#   script_name
# Arguments:
#   None
# Outputs:
#   Writes an absolute or PATH-resolved script path to STDOUT.
# Returns:
#   0 on success, 1 if the path cannot be resolved.
resolve_script_path() {
  local script_directory
  local resolved_directory
  local resolved_path

  case "${0}" in
    /*)
      printf '%s\n' "${0}"
      ;;
    */*)
      script_directory="${0%/*}"
      if ! resolved_directory="$(cd "${script_directory}" 2>/dev/null && pwd -P)"; then
        return 1
      fi
      printf '%s/%s\n' "${resolved_directory}" "${script_name}"
      ;;
    *)
      if ! resolved_path="$(command -v "${0}")"; then
        return 1
      fi
      case "${resolved_path}" in
        /*)
          printf '%s\n' "${resolved_path}"
          ;;
        *)
          script_directory="${resolved_path%/*}"
          if [ "${script_directory}" = "${resolved_path}" ]; then
            script_directory='.'
          fi
          if ! resolved_directory="$(cd "${script_directory}" 2>/dev/null && pwd -P)"; then
            return 1
          fi
          printf '%s/%s\n' "${resolved_directory}" "${resolved_path##*/}"
          ;;
      esac
      ;;
  esac

  return 0
}

###
# Find the remote represented by a remote-tracking upstream ref.
# Globals:
#   repository
# Arguments:
#   $1 - Full upstream ref name.
# Outputs:
#   Writes the best matching remote name to STDOUT, if found.
find_upstream_remote() {
  local full_upstream="${1}"
  local remote_list
  local candidate
  local best_match=''

  if ! remote_list="$(git -C "${repository}" remote)"; then
    return 1
  fi

  while IFS= read -r candidate; do
    [ -n "${candidate}" ] || continue
    case "${full_upstream}" in
      "refs/remotes/${candidate}/"*)
        if [ "${#candidate}" -gt "${#best_match}" ]; then
          best_match="${candidate}"
        fi
        ;;
      *) ;;
    esac
  done <<EOF
${remote_list}
EOF

  if [ -n "${best_match}" ]; then
    printf '%s\n' "${best_match}"
  fi

  return 0
}

###
# Report whether an interactive rebase is active.
# Globals:
#   git_directory
# Arguments:
#   None
# Returns:
#   0 if a rebase is active, 1 otherwise.
rebase_in_progress() {
  [ -d "${git_directory}/rebase-merge" ] \
    || [ -d "${git_directory}/rebase-apply" ]
}

###
# Abort a rebase left active by this script.
# Globals:
#   rebase_started
#   repository
# Arguments:
#   None
# Outputs:
#   Writes an error to STDERR if Git cannot restore the branch.
abort_active_rebase() {
  if [ "${rebase_started}" -eq 1 ] && rebase_in_progress; then
    if ! git -C "${repository}" rebase --abort; then
      print_error 'Automatic rebase abort failed; inspect the repository state.'
    fi
  fi
}

###
# Abort an active rebase during an abnormal exit.
# Arguments:
#   None
cleanup() {
  local exit_code="${?}"

  trap - EXIT HUP INT TERM
  abort_active_rebase
  exit "${exit_code}"
}

###
# Abort an active rebase and exit after an interrupting signal.
# Arguments:
#   $1 - Exit status associated with the signal.
handle_signal() {
  local exit_code="${1}"

  trap - EXIT HUP INT TERM
  abort_active_rebase
  exit "${exit_code}"
}

###
# Print the current commit message and identifying metadata.
# Globals:
#   repository
#   review_index
#   review_total
# Arguments:
#   None
# Outputs:
#   Writes commit information to STDOUT.
# Returns:
#   The exit status from git log.
show_current_commit() {
  printf '\nCommit %s of %s\n' "${review_index}" "${review_total}"
  printf '%s\n' '------------------------------------------------------------------------'
  git -C "${repository}" log -1 \
    --date='format:%Y-%m-%d %H:%M:%S %z' \
    --format='commit %H%nAuthor: %an <%ae>%nDate:   %ad%n%n%B' \
    'HEAD'
  printf '%s\n' '------------------------------------------------------------------------'
}

###
# Review one commit until the user accepts or aborts it.
# Globals:
#   repository
# Arguments:
#   None
# Outputs:
#   Writes prompts, commit messages, and requested diffs to STDOUT.
# Returns:
#   0 to continue, 2 to abort, 1 on input failure.
review_current_commit() {
  local answer

  while :; do
    if ! show_current_commit; then
      print_error 'Unable to display the current commit.'
      return 1
    fi

    printf '%s' '[e]dit, [d]iff, [n]ext, or [a]bort? '
    if ! IFS= read -r answer; then
      printf '\n' >&2
      print_error 'Unable to read a response.'
      return 1
    fi

    case "${answer}" in
      'e' | 'E' | 'edit' | 'Edit' | 'y' | 'Y' | 'yes' | 'Yes')
        if ! git -C "${repository}" commit --amend; then
          print_error 'The commit message was not changed.'
        fi
        ;;
      'd' | 'D' | 'diff' | 'Diff')
        if ! git -C "${repository}" diff 'HEAD^' 'HEAD' --; then
          print_error 'Unable to display the commit diff.'
        fi
        ;;
      'n' | 'N' | 'next' | 'Next')
        return 0
        ;;
      'a' | 'A' | 'abort' | 'Abort' | 'q' | 'Q' | 'quit' | 'Quit')
        return 2
        ;;
      *)
        printf '%s\n' 'Enter e, d, n, or a.'
        ;;
    esac
  done
}

###
# Validate repository state, fetch, and review all unpushed commits.
# Globals:
#   git_directory
#   rebase_started
#   repository
#   review_index
#   review_total
#   target_directory
#   upstream
# Arguments:
#   None
# Outputs:
#   Writes progress and errors to STDOUT or STDERR.
# Returns:
#   0 on success, 1 on failure or user abort.
run_review() {
  local current_branch
  local repository_status
  local operation_state
  local configured_remote=''
  local full_upstream=''
  local fetch_remote=''
  local upstream_oid
  local merge_commit
  local script_path
  local review_status
  local rebase_status

  if ! repository="$(git -C "${target_directory}" rev-parse --show-toplevel 2>/dev/null)"; then
    print_error "Not a Git repository: ${target_directory}"
    return 1
  fi
  if ! git_directory="$(git -C "${repository}" rev-parse --absolute-git-dir 2>/dev/null)"; then
    print_error 'Unable to determine the Git directory.'
    return 1
  fi
  if ! current_branch="$(git -C "${repository}" symbolic-ref --quiet --short 'HEAD')"; then
    print_error 'The repository is in detached HEAD state.'
    return 1
  fi

  for operation_state in \
    'rebase-merge' 'rebase-apply' 'sequencer' \
    'MERGE_HEAD' 'CHERRY_PICK_HEAD' 'REVERT_HEAD' 'BISECT_LOG'; do
    if [ -e "${git_directory}/${operation_state}" ]; then
      print_error 'Another Git history operation is already in progress.'
      return 1
    fi
  done

  if ! repository_status="$(
    git -C "${repository}" status --porcelain --untracked-files=all
  )"; then
    print_error 'Unable to inspect the working tree.'
    return 1
  fi
  if [ -n "${repository_status}" ]; then
    print_error 'The working tree must be clean, including untracked files.'
    return 1
  fi

  if [ -z "${upstream}" ]; then
    if ! upstream="$(
      git -C "${repository}" rev-parse \
        --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null
    )"; then
      print_error "Branch ${current_branch} has no configured upstream; use -u."
      return 1
    fi
  fi
  case "${upstream}" in
    -*)
      print_error 'The upstream ref must not start with a hyphen.'
      return 2
      ;;
    *) ;;
  esac

  configured_remote="$(
    git -C "${repository}" config --get "branch.${current_branch}.remote" \
      2>/dev/null || true
  )"
  full_upstream="$(
    git -C "${repository}" rev-parse --symbolic-full-name "${upstream}" \
      2>/dev/null || true
  )"
  if [ -n "${full_upstream}" ]; then
    fetch_remote="$(find_upstream_remote "${full_upstream}")"
  fi
  if [ -z "${fetch_remote}" ]; then
    fetch_remote="${configured_remote}"
  fi

  if [ -n "${fetch_remote}" ] && [ "${fetch_remote}" != '.' ]; then
    printf 'Fetching remote %s...\n' "${fetch_remote}"
    if ! git -C "${repository}" fetch "${fetch_remote}"; then
      print_error "Unable to fetch remote: ${fetch_remote}"
      return 1
    fi
  else
    printf '%s\n' 'No remote fetch is needed for the selected local upstream.'
  fi

  if ! upstream_oid="$(
    git -C "${repository}" rev-parse --verify "${upstream}^{commit}" 2>/dev/null
  )"; then
    print_error "Upstream does not resolve to a commit: ${upstream}"
    return 1
  fi
  if ! git -C "${repository}" merge-base --is-ancestor "${upstream_oid}" 'HEAD'; then
    print_error "Upstream ${upstream} is not an ancestor of ${current_branch}."
    print_error 'Reconcile the divergent branch before reviewing commit messages.'
    return 1
  fi

  if ! review_total="$(
    git -C "${repository}" rev-list --count "${upstream_oid}..HEAD"
  )"; then
    print_error 'Unable to count unpushed commits.'
    return 1
  fi
  if [ "${review_total}" -eq 0 ]; then
    printf 'No unpushed commits relative to %s.\n' "${upstream}"
    return 0
  fi

  if ! merge_commit="$(
    git -C "${repository}" rev-list \
      --min-parents=2 --max-count=1 "${upstream_oid}..HEAD"
  )"; then
    print_error 'Unable to inspect unpushed commits for merges.'
    return 1
  fi
  if [ -n "${merge_commit}" ]; then
    print_error 'The unpushed range contains a merge commit.'
    print_error 'Merge commits are intentionally unsupported to avoid changing topology.'
    return 1
  fi

  if ! script_path="$(resolve_script_path)"; then
    print_error 'Unable to resolve the helper path.'
    return 1
  fi
  GIT_REVIEW_UNPUSHED_SCRIPT="${script_path}"
  export GIT_REVIEW_UNPUSHED_SCRIPT
  # Git evaluates this value as a shell command. The deferred, quoted
  # expansion safely supports helper paths containing shell metacharacters.
  # shellcheck disable=SC2016,SC2089
  GIT_SEQUENCE_EDITOR='"${GIT_REVIEW_UNPUSHED_SCRIPT}" --internal-sequence-editor'
  # shellcheck disable=SC2090 # Git, not this shell, evaluates the command.
  export GIT_SEQUENCE_EDITOR

  printf 'Reviewing %s unpushed commit(s) relative to %s.\n' \
    "${review_total}" "${upstream}"
  rebase_started='1'
  trap cleanup EXIT
  trap 'handle_signal 129' HUP
  trap 'handle_signal 130' INT
  trap 'handle_signal 143' TERM

  git -C "${repository}" -c 'rebase.updateRefs=false' rebase \
    --interactive --no-autosquash --keep-empty "${upstream_oid}"
  rebase_status="${?}"
  if [ "${rebase_status}" -ne 0 ]; then
    print_error 'Unable to start the review rebase.'
    return 1
  fi

  while rebase_in_progress; do
    review_index=$((review_index + 1))
    review_current_commit
    review_status="${?}"
    if [ "${review_status}" -eq 2 ]; then
      if ! git -C "${repository}" rebase --abort; then
        print_error 'Unable to abort the rebase.'
        return 1
      fi
      rebase_started='0'
      trap - EXIT HUP INT TERM
      printf '%s\n' 'Review aborted; the original branch was restored.'
      return 1
    fi
    if [ "${review_status}" -ne 0 ]; then
      return 1
    fi

    git -C "${repository}" rebase --continue
    rebase_status="${?}"
    if [ "${rebase_status}" -ne 0 ]; then
      print_error 'The rebase could not continue; restoring the original branch.'
      return 1
    fi
  done

  rebase_started='0'
  trap - EXIT HUP INT TERM
  printf '%s\n' 'All unpushed commit messages were reviewed.'
  return 0
}

###
# Main entry point.
# Arguments:
#   $@ - Command-line arguments.
main() {
  local parse_status

  if [ "${1:-}" = '--internal-sequence-editor' ]; then
    if [ "$#" -ne 2 ]; then
      print_error 'Invalid internal sequence-editor invocation.'
      exit 1
    fi
    prepare_rebase_todo "${2}"
    exit "${?}"
  fi

  require_cmd 'git'
  parse_args "$@"
  parse_status="${?}"
  if [ "${parse_status}" -ne 0 ]; then
    exit "${parse_status}"
  fi
  if [ ! -t 0 ] || [ ! -t 1 ]; then
    print_error 'This interactive helper requires a terminal.'
    exit 1
  fi

  run_review
}

main "$@"
