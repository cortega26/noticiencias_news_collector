#!/usr/bin/env bash
set -euo pipefail
WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT
echo "not the real binary" > "$WORKDIR/gitleaks.tar.gz"
echo "0000000000000000000000000000000000000000000000000000000000000000  gitleaks.tar.gz" > "$WORKDIR/expected.sha256"
if (cd "$WORKDIR" && sha256sum -c expected.sha256) 2>/dev/null; then
  echo "FAIL: checksum verification did not catch a tampered/corrupted file"
  exit 1
fi
echo "PASS: sha256sum -c correctly rejects a mismatched file (exit $?)"
