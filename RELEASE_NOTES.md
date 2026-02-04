# Release Notes: v1.3.2 Security & Workflow Hardening

**Release Date:** 2026-02-04
**Type:** Patch Release (Security & Ops)

## 🚀 Key Changes

### 1. Security & Hygiene

- **Consolidated Workflows**: Consolidated security scanning into `ci.yml` by removing redundant `security.yml` and `audit-security.yml` workflows.
- **False Positive Reduction**: Applied strict `# nosec` suppression to known-safe internal scripts (e.g. `scripts/ops/purge_short_articles.py`), eliminating noise from Bandit scans.

### 2. Developer Experience

- **Cleaner Local Scans**: Added `temp/` to Bandit excludes in `pyproject.toml`.
- **CI Reliability**: Fixed Bandit integration in CI (`set -e` vs exit codes) to ensure the Security Gate runs reliably.

---

# Release Notes: v1.3.1 Snapshot-First Quality Gate

**Release Date:** 2026-01-31
**Type:** Patch Release (Reliability Hardening)

## 🚀 Key Changes

### 1. Snapshot-First Quality Gate

The editorial validation pipeline is now **CI-Safe** and **Deterministic**.

- **Validator**: `make quality-gate` runs offline (<1s) without LLM calls.
- **Provenance**: Snapshots (`snapshot.json`) are cryptographically stamped (`_meta`). Manual edits are forbidden.

### 2. Deterministic Repair Layer

Introduced `EditorAgent._repair_output()` to auto-correct minor model drift:

- **Headlines**: Automatically injects missing mandatory keys (`pregunta`, `benefit`).
- **Length**: Enforces strict 2.5x input/output ratio via deterministic truncation.

### 3. Developer Workflow

- New Command: `make prepush` runs the full test suite + quality gate.

## 🛠️ Usage

**Run Local Gate (Recommended before push):**

```bash
make prepush
```

**Regenerate Snapshots (Only on baseline change):**

```bash
make quality-gate-refresh
```

> **Warning**: Requires local LLM. Check `git diff` carefully before committing.

## 📦 Integrity Rules

- ❌ **Never** manually edit `snapshot.json`.
- ✅ **Always** review `snapshot.json` diffs after refresh.
