#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'USAGE'
Usage: scripts/coverage_ratcheter.sh <command> [--base-ref <ref>]

Commands:
  record   Persist the current coverage totals as the ratchet baseline.
  check    Validate coverage against the global threshold, baseline, and changed files.

Environment variables:
  COVERAGE_XML   Path to the Cobertura XML report (default: reports/coverage/coverage.xml).
  BASELINE_FILE  File used to store the baseline snapshot (default: .coverage-baseline).
  BASE_REF       Git ref used to compute changed modules (default: origin/main).
USAGE
}

if [[ $# -lt 1 ]]; then
    usage >&2
    exit 1
fi

COMMAND=""
BASE_REF=${BASE_REF:-origin/main}
POSITIONAL=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        record|check)
            if [[ -n "$COMMAND" ]]; then
                echo "[coverage-ratchet] command already specified: $COMMAND" >&2
                usage >&2
                exit 1
            fi
            COMMAND="$1"
            shift
            ;;
        --base-ref)
            if [[ $# -lt 2 ]]; then
                echo "[coverage-ratchet] --base-ref requires a value" >&2
                exit 1
            fi
            BASE_REF="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            POSITIONAL+=("$1")
            shift
            ;;
    esac
done

if [[ -z "$COMMAND" ]]; then
    echo "[coverage-ratchet] missing command" >&2
    usage >&2
    exit 1
fi

COVERAGE_XML=${COVERAGE_XML:-reports/coverage/coverage.xml}
BASELINE_FILE=${BASELINE_FILE:-.coverage-baseline}

ensure_coverage_xml() {
    if [[ ! -f "$COVERAGE_XML" ]]; then
        echo "[coverage-ratchet] coverage report '$COVERAGE_XML' not found. Run pytest with --cov first." >&2
        exit 1
    fi
}

snapshot_json() {
    python - <<'PY'
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
import os

coverage_path = Path(os.environ.get("COVERAGE_XML", "reports/coverage/coverage.xml"))
if not coverage_path.exists():
    print("{}", end="")
    sys.exit(0)

root = ET.parse(coverage_path).getroot()

def percent(value: str | None) -> float | None:
    if value in (None, ""):
        return None
    return round(float(value) * 100, 2)

def line_stats(cls):
    covered = 0
    total = 0
    branch_hits = 0
    branch_total = 0
    seen = set()
    for entry in cls.findall("lines/line"):
        number = entry.get("number")
        if number in seen:
            continue
        seen.add(number)
        total += 1
        try:
            hits = float(entry.get("hits", "0"))
        except ValueError:
            hits = 0.0
        if hits > 0:
            covered += 1
        if entry.get("branch") == "true":
            coverage = entry.get("condition-coverage", "")
            if "(" in coverage and "/" in coverage:
                fraction = coverage.split("(", 1)[1].split(")", 1)[0]
                try:
                    good, total_branches = fraction.split("/")
                    branch_hits += int(good)
                    branch_total += int(total_branches)
                except ValueError:
                    pass
    return covered, total, branch_hits, branch_total

files: dict[str, dict[str, float | None]] = {}
for cls in root.findall("packages/package/class"):
    filename = cls.get("filename")
    if not filename:
        continue
    cov, total, bhits, btotal = line_stats(cls)
    stats = files.setdefault(filename, {"covered": 0, "total": 0, "branch_hits": 0, "branch_total": 0})
    stats["covered"] += cov
    stats["total"] += total
    stats["branch_hits"] += bhits
    stats["branch_total"] += btotal

result = {
    "total_line": percent(root.get("line-rate")) or 0.0,
    "total_branch": percent(root.get("branch-rate")),
    "files": {},
}
for filename, stats in files.items():
    total = stats["total"]
    line_pct = 100.0 if total == 0 else round(stats["covered"] / total * 100, 2)
    branch_pct = None
    if stats["branch_total"] > 0:
        branch_pct = round(stats["branch_hits"] / stats["branch_total"] * 100, 2)
    result["files"][filename] = {"line": line_pct, "branch": branch_pct}

print(json.dumps(result))
PY
}

changed_modules() {
    local base_ref="$1"
    if git rev-parse --verify "$base_ref" >/dev/null 2>&1; then
        local merge_base
        merge_base=$(git merge-base HEAD "$base_ref")
        git diff --name-only "$merge_base" HEAD -- 'src/**/*.py'
    elif git rev-parse --verify HEAD^ >/dev/null 2>&1; then
        git diff --name-only HEAD^ HEAD -- 'src/**/*.py'
    else
        git ls-files 'src/**/*.py'
    fi
}

if [[ "$COMMAND" == "record" ]]; then
    ensure_coverage_xml
    SNAPSHOT=$(snapshot_json)
    if [[ -z "$SNAPSHOT" ]]; then
        echo "[coverage-ratchet] unable to parse coverage report" >&2
        exit 1
    fi
    SNAPSHOT_JSON="$SNAPSHOT" python - <<'PY'
import json
from datetime import datetime, timezone
from pathlib import Path
import sys
import os

baseline_path = Path(os.environ.get("BASELINE_FILE", ".coverage-baseline"))
baseline_path.write_text(
    json.dumps(
        {
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "total_line": json.loads(os.environ["SNAPSHOT_JSON"])["total_line"],
            "total_branch": json.loads(os.environ["SNAPSHOT_JSON"]).get("total_branch"),
        },
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)
print(f"[coverage-ratchet] baseline recorded at {baseline_path}")
PY
    exit 0
fi

if [[ "$COMMAND" == "check" ]]; then
    ensure_coverage_xml
    if [[ ! -f "$BASELINE_FILE" ]]; then
        echo "[coverage-ratchet] baseline file '$BASELINE_FILE' missing. Run scripts/coverage_ratcheter.sh record" >&2
        exit 1
    fi
    SNAPSHOT=$(snapshot_json)
    if [[ -z "$SNAPSHOT" ]]; then
        echo "[coverage-ratchet] unable to parse coverage report" >&2
        exit 1
    fi
    mapfile -t CHANGED < <(changed_modules "$BASE_REF")
    CHANGED_MODULES=$(printf "%s\n" "${CHANGED[@]}") SNAPSHOT_JSON="$SNAPSHOT" python - <<'PY'
import json
import os
import sys
from pathlib import Path

snapshot = json.loads(os.environ["SNAPSHOT_JSON"])
baseline_path = Path(os.environ.get("BASELINE_FILE", ".coverage-baseline"))
if not baseline_path.exists():
    print(
        f"[coverage-ratchet] baseline file '{baseline_path}' missing. Run scripts/coverage_ratcheter.sh record",
        file=sys.stderr,
    )
    sys.exit(1)
baseline = json.loads(baseline_path.read_text("utf-8"))

minimum_global = 80.0
minimum_changed = 90.0
minimum_branch = 70.0

current_total = snapshot["total_line"]
if current_total + 1e-6 < minimum_global:
    print(f"[coverage-ratchet] Global coverage {current_total:.2f}% fell below {minimum_global:.0f}%", file=sys.stderr)
    sys.exit(1)

baseline_total = baseline.get("total_line", 0.0)
if current_total + 0.05 < baseline_total:
    print(
        f"[coverage-ratchet] Coverage {current_total:.2f}% dropped below baseline {baseline_total:.2f}%",
        file=sys.stderr,
    )
    sys.exit(1)

changed = [line.strip() for line in os.environ.get("CHANGED_MODULES", "").splitlines() if line.strip()]
files = snapshot.get("files", {})
missing = []
violations = []
branch_violations = []
for path in changed:
    stats = files.get(path)
    if stats is None:
        missing.append(path)
        continue
    line_cov = stats.get("line", 0.0)
    if line_cov + 1e-6 < minimum_changed:
        violations.append((path, line_cov))
    branch_cov = stats.get("branch")
    if branch_cov is not None and branch_cov + 1e-6 < minimum_branch:
        branch_violations.append((path, branch_cov))

if missing:
    print(
        "[coverage-ratchet] Coverage data missing for changed modules: " + ", ".join(sorted(missing)),
        file=sys.stderr,
    )
    sys.exit(1)

if violations:
    msgs = ", ".join(f"{path} ({value:.2f}%)" for path, value in violations)
    print(
        f"[coverage-ratchet] Changed modules below {minimum_changed:.0f}% line coverage: {msgs}",
        file=sys.stderr,
    )
    sys.exit(1)

if branch_violations:
    msgs = ", ".join(f"{path} ({value:.2f}%)" for path, value in branch_violations)
    print(
        f"[coverage-ratchet] Branch coverage below {minimum_branch:.0f}% for: {msgs}",
        file=sys.stderr,
    )
    sys.exit(1)

print(
    f"[coverage-ratchet] OK — total {current_total:.2f}%, baseline {baseline_total:.2f}%, changed files passed",
    file=sys.stderr,
)
PY
fi
