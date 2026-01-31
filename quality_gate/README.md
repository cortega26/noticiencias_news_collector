# Quality Gate (Snapshot-First)

This directory contains the "Golden Set" of articles used to prevent editorial regressions.

## Philosophy

**CI must never call an LLM.**
To ensure deterministic, fast, and cost-effective testing, we use a **Snapshot-First** approach.

1.  **Snapshots (`snapshot.json`)**: Store the authoritative output of the pipeline for a given model version.
2.  **Expectations (`expected.json`)**: Define invariants that the snapshot MUST uphold (structure, forbidden phrases, etc.).

## Usage

### 1. Verification (CI / Local Default)

Run this to verify that existing snapshots meet expectations. **Does not use Ollama.**

```bash
make quality-gate
```

### 2. Regeneration (Manual Only)

Run this ONLY when:

- You have upgraded the model (e.g. Llama 3.2 -> 3.3).
- You have intentionally changed the prompt.
- You accept that the "Golden" output effectively changes.

```bash
make quality-gate-refresh
```

**Warning:** This will overwrite `snapshot.json`. You must review the git diffs manually to ensure the new output is acceptable.

## Structure

```
golden/
├── 01_frog/
│   ├── input.txt       # Source text
│   ├── expected.json   # Constraints (invariant)
│   ├── metadata.json   # Context
│   └── snapshot.json   # Generated Output (variable)
```
