#!/usr/bin/env bash
#
# release-prepare-markdown.sh - Convert relative links to absolute URLs in markdown files
#
# This script replaces relative repository links with absolute URLs to ensure
# they work correctly when rendered on package hosting platforms.

set -e
set -u

# Default values
branch="main"
orgname=""
reponame=""
url_base_raw=""
url_base_ui=""
simplify_html=0

# Usage function
usage() {
    cat >&2 <<EOF
Usage: ${0} [-b branch] [-o orgname] [-r reponame] [-a raw_url_base] [-u ui_url_base] [-s] file1 [file2 ...]

Options:
  -b  Branch name (default: main)
  -o  Organization name (default: parent directory name)
  -r  Repository name (default: current directory name)
  -a  Absolute URL base for raw files/images (default: https://raw.githubusercontent.com/ORG/REPO/refs/heads/BRANCH/)
  -u  Absolute URL base for other files (default: https://github.com/ORG/REPO/blob/BRANCH/)
  -s  Simplify well-known HTML snippets for platforms not supporting them

Arguments:
  file1 [file2 ...]  One or more markdown files to process
EOF
    exit 1
}

# Parse command line options
while getopts "b:o:r:a:u:sh" opt; do
    case ${opt} in
    b) branch="${OPTARG}" ;;
    o) orgname="${OPTARG}" ;;
    r) reponame="${OPTARG}" ;;
    a) url_base_raw="${OPTARG}" ;;
    u) url_base_ui="${OPTARG}" ;;
    s) simplify_html=1 ;;
    h) usage ;;
    *)
        usage
        ;;
    esac
done
shift $((OPTIND - 1))

# Check if at least one file is provided
if [ ${#} -eq 0 ]; then
    echo "Error: No files specified" >&2
    usage
fi

# Set default orgname if not provided (parent directory name)
if [ -z "${orgname}" ]; then
    orgname=$(basename "$(dirname "$(pwd)")")
fi

# Set default reponame if not provided (current directory name)
if [ -z "${reponame}" ]; then
    reponame=$(basename "$(pwd)")
fi

# Set default URL bases if not provided
if [ -z "${url_base_raw}" ]; then
    url_base_raw="https://raw.githubusercontent.com/${orgname}/${reponame}/refs/heads/${branch}"
fi

if [ -z "${url_base_ui}" ]; then
    url_base_ui="https://github.com/${orgname}/${reponame}/blob/${branch}"
fi

# Function to process a single file
process_file() {
    local file="${1}"
    local markdown_link_label="(([^]\`]|\`[^\`]*\`)*)"
    local tmpfile

    if [ ! -f "${file}" ]; then
        echo "Warning: File not found: ${file}" >&2
        return 1
    fi

    echo "Processing: ${file}"

    # Create a temporary file
    tmpfile=$(mktemp)

    # Read the file content
    cp "${file}" "${tmpfile}"

    # 1. Markdown images with ./ prefix (case insensitive extensions)
    #    ![alt](./path.png) -> ![alt](${url_base_raw}/path.png)
    sed -E -i "" "s#!\[([^]]*)\]\(\./([^)#[:space:]]+\.(png|jpe?g|svg|gif|webm|ico|pdf|zip|tar|gz|bz2|xz|mp4|webp)([?][^)#[:space:]]*)?)\)#![\1](${url_base_raw}/\2)#gI" "${tmpfile}" 2>/dev/null ||
        sed -E -i "s#!\[([^]]*)\]\(\./([^)#[:space:]]+\.(png|jpe?g|svg|gif|webm|ico|pdf|zip|tar|gz|bz2|xz|mp4|webp)([?][^)#[:space:]]*)?)\)#![\1](${url_base_raw}/\2)#gI" "${tmpfile}"

    # 2. Markdown images without ./ prefix (must not start with scheme, /, or #)
    #    ![alt](path.png) -> ![alt](${url_base_raw}/path.png)
    sed -E -i "" "s#!\[([^]]*)\]\(([A-Za-z0-9][^):#[:space:]]+\.(png|jpe?g|svg|gif|webm|ico|pdf|zip|tar|gz|bz2|xz|mp4|webp)([?][^)#[:space:]]*)?)\)#![\1](${url_base_raw}/\2)#gI" "${tmpfile}" 2>/dev/null ||
        sed -E -i "s#!\[([^]]*)\]\(([A-Za-z0-9][^):#[:space:]]+\.(png|jpe?g|svg|gif|webm|ico|pdf|zip|tar|gz|bz2|xz|mp4|webp)([?][^)#[:space:]]*)?)\)#![\1](${url_base_raw}/\2)#gI" "${tmpfile}"

    # 3. Markdown links with ./ prefix (not images)
    #    [text](./path) -> [text](${url_base_ui}/path)
    #    A path fragment is preserved; a pure anchor does not match.
    sed -E -i "" "s#([^!]|^)\[${markdown_link_label}\]\(\./([^)#[:space:]]+)(\#[^)[:space:]]*)?\)#\1[\2](${url_base_ui}/\4\5)#g" "${tmpfile}" 2>/dev/null ||
        sed -E -i "s#([^!]|^)\[${markdown_link_label}\]\(\./([^)#[:space:]]+)(\#[^)[:space:]]*)?\)#\1[\2](${url_base_ui}/\4\5)#g" "${tmpfile}"

    # 4. Markdown links without ./ prefix (must not start with scheme, /, or #)
    #    [text](path) -> [text](${url_base_ui}/path)
    #    Labels may contain ] inside backtick-delimited code spans.
    sed -E -i "" "s#([^!]|^)\[${markdown_link_label}\]\(([A-Za-z0-9][^):#[:space:]]+)(\#[^)[:space:]]*)?\)#\1[\2](${url_base_ui}/\4\5)#g" "${tmpfile}" 2>/dev/null ||
        sed -E -i "s#([^!]|^)\[${markdown_link_label}\]\(([A-Za-z0-9][^):#[:space:]]+)(\#[^)[:space:]]*)?\)#\1[\2](${url_base_ui}/\4\5)#g" "${tmpfile}"

    # 5. HTML href attributes with ./ prefix (case insensitive)
    #    href="./path" -> href="${url_base_ui}/path"
    sed -E -i "" "s#([Hh][Rr][Ee][Ff])[[:space:]]*=[[:space:]]*([\"'])\./([^\"'#[:space:]>]+)\2#\1=\2${url_base_ui}/\3\2#g" "${tmpfile}" 2>/dev/null ||
        sed -E -i "s#([Hh][Rr][Ee][Ff])[[:space:]]*=[[:space:]]*([\"'])\./([^\"'#[:space:]>]+)\2#\1=\2${url_base_ui}/\3\2#g" "${tmpfile}"

    # 6. HTML href attributes without ./ prefix (must not start with scheme, /, or #)
    #    href="path" -> href="${url_base_ui}/path"
    sed -E -i "" "s#([Hh][Rr][Ee][Ff])[[:space:]]*=[[:space:]]*([\"'])([A-Za-z0-9][^\"':#[:space:]>]*)\2#\1=\2${url_base_ui}/\3\2#g" "${tmpfile}" 2>/dev/null ||
        sed -E -i "s#([Hh][Rr][Ee][Ff])[[:space:]]*=[[:space:]]*([\"'])([A-Za-z0-9][^\"':#[:space:]>]*)\2#\1=\2${url_base_ui}/\3\2#g" "${tmpfile}"

    # 7. HTML src attributes with ./ prefix (case insensitive)
    #    src="./path" -> src="${url_base_raw}/path"
    sed -E -i "" "s#([Ss][Rr][Cc])[[:space:]]*=[[:space:]]*([\"'])\./([^\"'#[:space:]>]+)\2#\1=\2${url_base_raw}/\3\2#g" "${tmpfile}" 2>/dev/null ||
        sed -E -i "s#([Ss][Rr][Cc])[[:space:]]*=[[:space:]]*([\"'])\./([^\"'#[:space:]>]+)\2#\1=\2${url_base_raw}/\3\2#g" "${tmpfile}"

    # 8. HTML src attributes without ./ prefix (must not start with scheme, /, or #)
    #    src="path" -> src="${url_base_raw}/path"
    sed -E -i "" "s#([Ss][Rr][Cc])[[:space:]]*=[[:space:]]*([\"'])([A-Za-z0-9][^\"':#[:space:]>]*)\2#\1=\2${url_base_raw}/\3\2#g" "${tmpfile}" 2>/dev/null ||
        sed -E -i "s#([Ss][Rr][Cc])[[:space:]]*=[[:space:]]*([\"'])([A-Za-z0-9][^\"':#[:space:]>]*)\2#\1=\2${url_base_raw}/\3\2#g" "${tmpfile}"

    # 9. Simplify well-known HTML snippets (if -s is set)
    #
    # Converts blocks like:
    #   <div align="center" id="project-readme-header">
    #   <br>
    #   **bold text**
    #   [![alt](img_url)](link_url)
    #   <br>
    #   </div>
    # Into:
    #   **bold text** [alt](link_url)
    if [ "${simplify_html}" -eq 1 ]; then
        # 9a. Convert markdown image-in-link [![alt](img)](url) to plain link [alt](url)
        sed -E -i "" 's/\[!\[([^]]*)\]\([^)]*\)\]\(([^)]*)\)/[\1](\2)/g' "${tmpfile}" 2>/dev/null ||
            sed -E -i 's/\[!\[([^]]*)\]\([^)]*\)\]\(([^)]*)\)/[\1](\2)/g' "${tmpfile}"

        # 9b. Collapse <div ... id="project-readme-header">...</div> blocks
        #     into a single line, removing HTML tags and blank lines
        awk '
        /<div[^>]*id=["'"'"']?project-readme-header["'"'"']?/ {
            in_block = 1; content = ""; next
        }
        in_block && /<\/div>/ {
            in_block = 0
            gsub(/^[[:space:]]+|[[:space:]]+$/, "", content)
            if (content != "") print content
            next
        }
        in_block {
            line = $0
            gsub(/^[[:space:]]+|[[:space:]]+$/, "", line)
            if (line == "" || tolower(line) ~ /^<br[[:space:]]*\/?>$/) next
            if (content != "") content = content " "
            content = content line
            next
        }
        { print }
        ' "${tmpfile}" > "${tmpfile}.simplified" && mv "${tmpfile}.simplified" "${tmpfile}"
    fi

    # Show diff if there are changes
    if ! diff -q "${file}" "${tmpfile}" >/dev/null 2>&1; then
        echo ""
        echo "Changes for ${file}:"
        echo "----------------------------------------"
        diff -u "${file}" "${tmpfile}" || true
        echo "----------------------------------------"
        echo ""
    else
        echo "No changes needed for ${file}"
    fi

    # Replace original file with processed version
    mv "${tmpfile}" "${file}"

    echo "Completed: ${file}"
}

# Process each file
for file in "${@}"; do
    process_file "${file}"
done

echo "All files processed successfully"
