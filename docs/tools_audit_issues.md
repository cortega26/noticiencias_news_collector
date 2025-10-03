# Audit Issue Creation Tool

The `tools/audit_to_issues.sh` helper converts each `./audit/*.md` file into a GitHub issue so audit findings can be triaged inside the repository backlog.

## Prerequisites
- [GitHub CLI (`gh`)](https://cli.github.com/) installed and authenticated (`gh auth login`).
- `GH_TOKEN` exported in the shell. The token must grant `repo` scope for private repositories or `public_repo` for public repositories so the CLI can create issues on your behalf.
- Network connectivity to GitHub's API.

## Usage
```bash
# Dry-run: show the issue creation commands
make audit-issues AUDIT_ISSUES_FLAGS="-n"

# Create the issues in the current repository
make audit-issues
```

Behind the scenes the Makefile target calls:
```bash
./tools/audit_to_issues.sh [-n] [-- <additional gh issue create args>]
```

Each markdown file generates one issue with:
- Title: `Audit: <filename>`
- Labels: `audit,triage`
- Body: the line `See <path> for details.` followed by the file content.

Use the `--` separator to pass extra options directly to `gh issue create`, for example to target another repository:
```bash
./tools/audit_to_issues.sh -n -- --repo org/project --assignee your-user
```

## Configuration
| Name | Type | Default | Required | Description |
| --- | --- | --- | --- | --- |
| `GH_TOKEN` | string | _none_ | Yes | Personal access token used by `gh` to authenticate issue creation. |
| `AUDIT_ISSUES_FLAGS` | string | _empty_ | No | Optional Makefile variable forwarded to the script (e.g., `-n` for dry-run or `-- --repo org/project`). |

## Operational Notes
- The script exits early when no `./audit/*.md` files are present.
- Dry-run mode prints the exact `gh issue create` commands without executing them so you can review the payload first.
- Temporary files containing issue bodies are removed after each iteration.
