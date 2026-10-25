#!/usr/bin/env bash
# Check the installed tree, not just node_modules' existence. No network or install.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root/apps/admin"

if ! npm ls --depth=0 --include=dev >/dev/null 2>&1; then
  echo "admin: dependencies are missing or incompatible — run 'make admin-install', then retry." >&2
  echo "admin: inspect details with 'npm --prefix apps/admin ls --depth=0 --include=dev'." >&2
  exit 1
fi
