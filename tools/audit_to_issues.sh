#!/bin/sh
set -eu

usage() {
    cat <<'USAGE'
Usage: audit_to_issues.sh [-n] [-- <gh issue create args...>]

Create one GitHub issue per ./audit/*.md file with labels "audit,triage".

Options:
  -n    Dry-run; print gh commands without executing them.
  -h    Show this help message.

Any additional arguments provided after "--" are forwarded to "gh issue create".
USAGE
}

DRY_RUN=0
PASSTHRU_ARGS=""

while [ "$#" -gt 0 ]; do
    case "$1" in
        -n)
            DRY_RUN=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        --)
            shift
            PASSTHRU_ARGS="$*"
            break
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

if ! command -v gh >/dev/null 2>&1; then
    echo "Error: gh CLI is required but not found in PATH." >&2
    exit 1
fi

if [ "${GH_TOKEN:-}" = "" ]; then
    echo "Error: GH_TOKEN environment variable must be set." >&2
    exit 1
fi

set -- ./audit/*.md
if [ "$1" = "./audit/*.md" ] && [ ! -e "$1" ]; then
    echo "No audit markdown files found in ./audit." >&2
    exit 0
fi

for FILE in "$@"; do
    if [ ! -f "$FILE" ]; then
        continue
    fi

    BASENAME=$(basename "$FILE")
    TITLE="Audit: $BASENAME"
    BODY_FILE=$(mktemp)

    {
        printf 'See `%s` for details.\n\n' "$FILE"
        cat "$FILE"
    } >"$BODY_FILE"

    if [ "$DRY_RUN" -eq 1 ]; then
        printf 'gh issue create --title %s --label %s --body-file %s' \
            "'${TITLE}'" "'audit,triage'" "'${BODY_FILE}'"
        if [ -n "$PASSTHRU_ARGS" ]; then
            printf ' %s' "$PASSTHRU_ARGS"
        fi
        printf '\n'
    else
        if [ -n "$PASSTHRU_ARGS" ]; then
            # shellcheck disable=SC2086
            gh issue create --title "$TITLE" --label "audit,triage" --body-file "$BODY_FILE" $PASSTHRU_ARGS
        else
            gh issue create --title "$TITLE" --label "audit,triage" --body-file "$BODY_FILE"
        fi
    fi

    rm -f "$BODY_FILE"
done
