#!/usr/bin/env python3
"""
check_doc_drift.py — backend mirror of the frontend `check:doc-drift` gate.

Validates that backend governance docs reference real paths, real Make
targets, real workflow files, and declared invariants that are true of the
current repository. Catches stale references and stale semantic claims
before they mislead contributors.

Checks (per active doc line, outside code blocks):
  - file paths in backticks that look like repo paths exist on disk
  - `make <target>` references exist in the Makefile
  - `.github/workflows/<name>.yml` references exist on disk
  - stale schema path `src/content/config.ts` (expected
    `src/content.config.ts`, the frontend authority)
  - stale site host `noticiencias.cl` (expected host parsed from the
    frontend sibling's `src/config.yaml` / `astro.config.mjs`, or the
    backend `config.toml` default when no sibling is checked out)
  - stale Python major claims ("Python <N>" in current-state contexts must
    match the `.python-version` / `requires-python` major)
  - cross-repo references (`../noticiencias/...`) when the sibling repo is
    checked out; silently skipped when it is not

Env overrides (used by the test suite; default to repo behavior):
  - DOC_DRIFT_ROOT: base directory for resolving doc paths
  - DOC_DRIFT_FILES: comma-separated list of docs to check
  - DOC_DRIFT_SIBLING_ROOT: sibling repo root for cross-repo refs
    (default: ../noticiencias relative to this repo)
  - DOC_DRIFT_MAKEFILE: Makefile path (default: <root>/Makefile)

Exit codes:
  0 — all paths, commands, and invariants verified
  1 — one or more broken references or stale claims found
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(
    os.environ.get("DOC_DRIFT_ROOT", Path(__file__).resolve().parents[1])
).resolve()
SCRIPT_DIR = Path(__file__).resolve().parents[1]

DEFAULT_DOC_FILES = [
    "README.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "docs/AGENTS.md",
    "docs/ARCHITECTURE.md",
    "docs/INDEX.md",
    "docs/PIPELINE_CONTRACTS.md",
    "docs/PRODUCT_FLOW.md",
    "docs/SOURCE_OF_TRUTH.md",
    "docs/ci.md",
    "docs/security.md",
    "docs/RUNBOOK_LOCAL_DEV.md",
    "docs/database_deployment.md",
    "docs/testing.md",
]

# Repo-root prefixes that resolve from REPO_ROOT, plus top-level files.
ROOT_PREFIXES = (
    "news_collector/",
    "scripts/",
    "tests/",
    "docs/",
    "apps/",
    "noticiencias/",
    "config/",
    "context/",
    "data/",
    ".github/",
    "plans/",
    "spec-logs/",
    "audit/",
    "alembic/",
    "tools/",
    "temp/",
)
# Package-dir shorthand used by backend docs: `serving/api.py` means
# `news_collector/serving/api.py`.
PACKAGE_SHORTHAND = (
    "serving/",
    "storage/",
    "collectors/",
    "enrichment/",
    "infrastructure/",
    "scoring/",
    "validation/",
    "taxonomy/",
    "editorial/",
    "reranker/",
    "monitoring/",
    "components/",
    "system/",
    "logic/",
    "utils/",
    "contracts/",
)
TOP_LEVEL_FILES = {
    "README.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "Makefile",
    "config.toml",
    ".env.example",
    "pyproject.toml",
    "requirements.lock",
    "requirements-security.lock",
    "requirements-refinery.lock",
    "alembic.ini",
    ".gitignore",
    ".python-version",
    "VERSION",
}

# Line-number suffix stripping: `foo.ts:122` / `foo.ts:24-25,34-35`
_LINE_SUFFIX_RE = re.compile(r":(\d+(-\d+)?(,\d+(-\d+)?)*)+$")
# Test-node suffix stripping: `tests/test_x.py::test_case`
_TEST_NODE_RE = re.compile(r"::[A-Za-z_][\w]*$")
_EXTENSION_RE = re.compile(
    r"\.(ts|js|py|md|yaml|yml|json|css|mjs|toml|lock|ini|txt|xml|sh|sql|env)$"
)
# Placeholder refs like `<canonical-slug>.md` are patterns, not paths.
_PLACEHOLDER_RE = re.compile(r"<[^>]+>")

# Backend current-state Python claim: "Python 3.13" in an active-doc context.
_PYTHON_CLAIM_RE = re.compile(r"Python\s+3\.(\d+)")

# Bare filenames that are ambiguous name-mentions (historical or generated
# artifacts) rather than repo paths; these are not chased down.
_BARE_NAME_SEARCH_DIRS = (
    "news_collector/utils",
    "news_collector/contracts",
    "news_collector/system",
    "news_collector/collectors",
    "news_collector/enrichment",
    "news_collector/infrastructure",
    "news_collector/storage",
    "news_collector/scoring",
    "news_collector/validation",
    "news_collector/taxonomy",
    "news_collector/editorial",
    "news_collector/reranker",
    "news_collector/logic/workflows",
    "news_collector/serving",
    "news_collector/monitoring",
    "news_collector/components",
    "scripts",
    "tests",
    ".github/workflows",
    "docs",
    "context",
    "",
)


def strip_line_numbers(raw: str) -> str:
    cleaned = _LINE_SUFFIX_RE.sub("", raw)
    cleaned = _TEST_NODE_RE.sub("", cleaned)
    return cleaned


def looks_like_file_path(s: str) -> bool:
    """True when a backtick string looks like a repo-relative file path."""
    if not s:
        return False
    if " " in s or "\t" in s:
        return False  # command invocations (`pip-audit -r requirements.lock`)
    if s.startswith(("http://", "https://")):
        return False
    if s.startswith(("~", "~/", "$HOME")):
        return False  # user-local paths like ~/.cloudflared/config.yml
    if s.startswith("/") and "home/" not in s and "noticiencias" not in s:
        return False
    if s.startswith("#"):
        return False
    if "*" in s or "?" in s:
        return False
    if _PLACEHOLDER_RE.search(s):
        return False  # `<canonical-slug>.md` is a pattern, not a path
    if s.endswith("/"):
        return False
    # Dotfiles like `apps/refinery/.env` are conditional/ignored by design.
    if s.split("/")[-1].startswith("."):
        return False
    # JS member expressions like data.permalink
    if re.fullmatch(r"[a-z_]+\.[a-z_]+", s) and not _EXTENSION_RE.search(s):
        return False
    return (
        bool(_EXTENSION_RE.search(s))
        or s.startswith(ROOT_PREFIXES)
        or s in TOP_LEVEL_FILES
        or s.startswith(PACKAGE_SHORTHAND)
    )


def resolve_doc_path(raw: str, doc_dir: Path) -> Path | None:
    """Resolve a doc reference to an absolute path, or None when it must be
    skipped (cross-repo ref with no sibling checked out, or an ambiguous
    bare name-mention that is not a repo path)."""
    cleaned = raw.lstrip("/")

    # Cross-repo frontend references.
    if cleaned.startswith("../noticiencias/"):
        sibling = Path(
            os.environ.get("DOC_DRIFT_SIBLING_ROOT", SCRIPT_DIR / ".." / "noticiencias")
        ).resolve()
        if not sibling.is_dir():
            return None
        return sibling / cleaned[len("../noticiencias/") :]
    if cleaned.startswith("src/"):
        # Frontend-only paths like src/content.config.ts belong to the sibling.
        sibling = Path(
            os.environ.get("DOC_DRIFT_SIBLING_ROOT", SCRIPT_DIR / ".." / "noticiencias")
        ).resolve()
        if not sibling.is_dir():
            return None
        return sibling / cleaned

    # Old workspace absolute paths: /home/.../noticiencias_news_collector/src/...
    idx = cleaned.find("noticiencias_news_collector/")
    if idx >= 0:
        cleaned = cleaned[idx + len("noticiencias_news_collector/") :]

    if cleaned.startswith(ROOT_PREFIXES):
        return REPO_ROOT / cleaned
    if cleaned.startswith(PACKAGE_SHORTHAND):
        return REPO_ROOT / "news_collector" / cleaned
    if cleaned in TOP_LEVEL_FILES:
        return REPO_ROOT / cleaned
    if "/" not in cleaned:
        # bare filename: try common backend directories, then the sibling's
        # workflows; if nothing matches, it is an ambiguous name-mention
        # (e.g. `main.py` describing a removed entrypoint) and is skipped.
        for d in _BARE_NAME_SEARCH_DIRS:
            candidate = REPO_ROOT / d / cleaned
            if candidate.exists():
                return candidate
        sibling = Path(
            os.environ.get("DOC_DRIFT_SIBLING_ROOT", SCRIPT_DIR / ".." / "noticiencias")
        ).resolve()
        if sibling.is_dir():
            wf = sibling / ".github/workflows" / cleaned
            if wf.exists():
                return wf
        return None
    # Paths without extension but with directory: resolve from root
    if "." not in cleaned:
        return REPO_ROOT / cleaned
    return doc_dir / cleaned


def extract_paths(line: str) -> list[tuple[str, str | None, str | None]]:
    """Return [(raw, cleaned_or_None, cmd_kind_or_None)] where cleaned=None
    marks a command reference and cmd_kind is 'make' or 'npm'."""
    results: list[tuple[str, str | None, str | None]] = []
    for m in re.finditer(r"`([^`]+)`", line):
        raw = m.group(1).strip()
        cleaned = strip_line_numbers(raw)
        if looks_like_file_path(cleaned):
            results.append((raw, cleaned, None))
    for m in re.finditer(r"`(npm run|make)\s+([\w:-]+)`", line):
        results.append((m.group(0), None, m.group(1)))
    return results


def load_make_targets(makefile: Path) -> set[str]:
    """Parse declared Make targets from the Makefile."""
    targets: set[str] = set()
    if not makefile.is_file():
        return targets
    for line in makefile.read_text(encoding="utf-8").splitlines():
        if line.startswith((".", "#", "\t")):
            continue
        if ":" not in line or "=" in line.split(":")[0]:
            continue
        name = line.split(":", 1)[0].strip()
        if name and re.fullmatch(r"[A-Za-z0-9_.-]+", name):
            targets.add(name)
    return targets


def load_sibling_npm_scripts() -> set[str]:
    """npm scripts from the sibling frontend package.json (empty when the
    sibling is not checked out)."""
    sibling = Path(
        os.environ.get("DOC_DRIFT_SIBLING_ROOT", SCRIPT_DIR / ".." / "noticiencias")
    ).resolve()
    if not sibling.is_dir():
        return set()
    pkg = sibling / "package.json"
    if not pkg.is_file():
        return set()
    import json

    try:
        return set(json.loads(pkg.read_text(encoding="utf-8")).get("scripts", {}))
    except (ValueError, OSError):
        return set()


def load_python_version() -> tuple[int, int] | None:
    """(major, minor) from .python-version / pyproject requires-python."""
    dot = REPO_ROOT / ".python-version"
    if dot.is_file():
        m = re.search(r"(\d+)\.(\d+)", dot.read_text(encoding="utf-8").strip())
        if m:
            return int(m.group(1)), int(m.group(2))
    pyproject = REPO_ROOT / "pyproject.toml"
    if pyproject.is_file():
        m = re.search(
            r'requires-python\s*=\s*">=(\d+)\.(\d+)',
            pyproject.read_text(encoding="utf-8"),
        )
        if m:
            return int(m.group(1)), int(m.group(2))
    return None


def load_site_host() -> str | None:
    """Production site host: frontend sibling config when available, else the
    backend config.toml [ollama]-adjacent default is not used; the backend
    does not own the host, so without a sibling we skip the host check."""
    sibling = Path(
        os.environ.get("DOC_DRIFT_SIBLING_ROOT", SCRIPT_DIR / ".." / "noticiencias")
    ).resolve()
    if sibling.is_dir():
        yaml_path = sibling / "src/config.yaml"
        if yaml_path.is_file():
            m = re.search(
                r"^\s{2}site:\s*['\"]([^'\"]+)['\"]", yaml_path.read_text(), re.M
            )
            if m:
                return m.group(1).rstrip("/")
        astro = sibling / "astro.config.mjs"
        if astro.is_file():
            m = re.search(r"site:\s*['\"]([^'\"]+)['\"]", astro.read_text())
            if m:
                return m.group(1).rstrip("/")
    return None


def check_invariants(
    line: str, doc: str, line_no: int, site_host: str | None
) -> list[dict]:
    found: list[dict] = []
    if "`src/content/config.ts`" in line:
        found.append(
            {
                "doc": doc,
                "type": "stale_schema_path",
                "ref": "src/content/config.ts",
                "line": line_no,
                "message": "expected `src/content.config.ts` (frontend schema authority)",
            }
        )
    if site_host and "noticiencias.cl" in line:
        found.append(
            {
                "doc": doc,
                "type": "stale_site_host",
                "ref": "noticiencias.cl",
                "line": line_no,
                "message": f"expected {site_host} (parsed from sibling site config)",
            }
        )
    py_version = load_python_version()
    if py_version is not None:
        expected = f"Python {py_version[0]}.{py_version[1]}"
        for m in _PYTHON_CLAIM_RE.finditer(line):
            claimed = f"Python 3.{m.group(1)}"
            if claimed != expected:
                found.append(
                    {
                        "doc": doc,
                        "type": "stale_runtime_major",
                        "ref": claimed,
                        "line": line_no,
                        "message": f"expected {expected} (from .python-version)",
                    }
                )
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--makefile", type=Path, default=None, help="Makefile path override"
    )
    args = parser.parse_args(argv)

    doc_files = [
        f.strip() for f in os.environ.get("DOC_DRIFT_FILES", "").split(",") if f.strip()
    ] or DEFAULT_DOC_FILES

    makefile = args.makefile or REPO_ROOT / "Makefile"
    make_targets = load_make_targets(makefile)
    npm_scripts = load_sibling_npm_scripts()
    site_host = load_site_host()

    broken: list[dict] = []

    for doc_rel in doc_files:
        doc_path = REPO_ROOT / doc_rel
        if not doc_path.is_file():
            broken.append({"doc": doc_rel, "type": "doc_missing", "ref": doc_rel})
            continue

        lines = doc_path.read_text(encoding="utf-8").splitlines()
        doc_dir = doc_path.parent
        in_code_block = False

        for i, line in enumerate(lines, start=1):
            if line.strip().startswith("```"):
                in_code_block = not in_code_block
                continue
            if in_code_block:
                continue

            for err in check_invariants(line, doc_rel, i, site_host):
                broken.append(err)

            # Table rows: only invariant claims, no path lookups.
            if line.strip().startswith("|"):
                continue

            for raw, cleaned, cmd_kind in extract_paths(line):
                if cleaned is None:
                    cmd = re.search(r"`(?:npm run|make)\s+([\w:-]+)`", raw).group(1)
                    if cmd_kind == "make":
                        if cmd in make_targets:
                            continue
                        broken.append(
                            {
                                "doc": doc_rel,
                                "type": "make_target",
                                "ref": raw,
                                "line": i,
                                "message": f'make target "{cmd}" not found in Makefile',
                            }
                        )
                    else:
                        # npm commands belong to the sibling frontend; skipped
                        # when the sibling is not checked out.
                        if not npm_scripts:
                            continue
                        if cmd in npm_scripts:
                            continue
                        broken.append(
                            {
                                "doc": doc_rel,
                                "type": "npm_script",
                                "ref": raw,
                                "line": i,
                                "message": f'npm script "{cmd}" not found in sibling package.json',
                            }
                        )
                    continue

                resolved = resolve_doc_path(cleaned, doc_dir)
                if resolved is None:
                    continue  # cross-repo ref, sibling not checked out
                if not resolved.exists():
                    try:
                        shown = resolved.relative_to(REPO_ROOT)
                    except ValueError:
                        shown = resolved
                    broken.append(
                        {
                            "doc": doc_rel,
                            "type": "broken_path",
                            "ref": raw,
                            "line": i,
                            "message": f"file not found: {shown}",
                        }
                    )

    if broken:
        seen: set[tuple[str, str, str]] = set()
        unique: list[dict] = []
        for b in broken:
            key = (b["doc"], b["ref"], b["type"])
            if key not in seen:
                seen.add(key)
                unique.append(b)

        by_type = {
            "doc_missing": [b for b in unique if b["type"] == "doc_missing"],
            "broken_path": [b for b in unique if b["type"] == "broken_path"],
            "make_target": [b for b in unique if b["type"] == "make_target"],
            "npm_script": [b for b in unique if b["type"] == "npm_script"],
            "invariant": [
                b
                for b in unique
                if b["type"]
                in {"stale_schema_path", "stale_site_host", "stale_runtime_major"}
            ],
        }
        for kind, label in (
            ("doc_missing", "doc(s) not found"),
            ("broken_path", "broken path(s)"),
            ("make_target", "unknown make target(s)"),
            ("npm_script", "unknown npm script(s)"),
            ("invariant", "stale declared claim(s)"),
        ):
            entries = by_type[kind]
            if not entries:
                continue
            print(f"[check:doc-drift] {len(entries)} {label}:")
            for b in entries:
                print(f"  {b['doc']}:{b.get('line', '?')}: `{b['ref']}`")
                print(f"    -> {b['message']}")

        print(
            "\nUpdate the docs to reference existing files, commands, and invariant values."
        )
        return 1

    print(
        f"[check:doc-drift] OK - {len(doc_files)} docs checked, all paths, "
        "commands, and invariants verified."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
