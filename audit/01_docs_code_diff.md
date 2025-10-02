# Docs vs Code Consistency Audit

## Methodology
- Parsed all Markdown under the repository root and `docs/` to inventory referenced modules, commands, and configuration keys.
- Generated an AST-based catalog of public Python callables to verify whether documented modules/functions exist in code.
- Flattened `config.toml` and parsed `.env.example` to cross-check each key against repository usage via `rg` searches.
- Flagged mismatches where documentation references stale files, missing tooling, or configuration patterns unsupported by the current codebase.

## Findings & Fixes

### 1. `.env.example` uses unsupported keys
- The template documents bare variables such as `ENV`, `COLLECTION_INTERVAL`, and `WEIGHT_SOURCE`, but the loader only ingests environment overrides with the `NOTICIENCIAS__` prefix and double-underscore segments.【F:.env.example†L1-L109】【F:noticiencias/config_manager.py†L146-L157】【F:noticiencias/config_manager.py†L356-L384】
- 50 of the 63 documented keys are unused anywhere else in the repo, confirming the template no longer matches runtime expectations.【17c5f9†L1-L1】【65c00f†L1-L19】
- **Impact:** Operators relying on this template will export variables the system never reads, leading to silent misconfiguration.
- **Proposed patch:** convert the template to the new names (e.g., `NOTICIENCIAS__APP__ENVIRONMENT`, `NOTICIENCIAS__COLLECTION__COLLECTION_INTERVAL_HOURS`, `NOTICIENCIAS__SCORING__WEIGHTS__SOURCE_CREDIBILITY`) and drop obsolete aliases. For example:
  ```diff
  -ENV=development
  -DEBUG=true
  -COLLECTION_INTERVAL=6
  -REQUEST_TIMEOUT=30
  +NOTICIENCIAS__APP__ENVIRONMENT=development
  +NOTICIENCIAS__APP__DEBUG=true
  +NOTICIENCIAS__COLLECTION__COLLECTION_INTERVAL_HOURS=6
  +NOTICIENCIAS__COLLECTION__REQUEST_TIMEOUT_SECONDS=30
  ```
  Extend this renaming across scoring, enrichment, dedupe, and logging entries, keeping comments aligned with the nested schema in `noticiencias.config_schema`.

### 2. `AGENTS.md` references defunct files and modules
- Architecture snapshot still cites `[utils.parse] → [collectors.parsers]`, yet no such modules exist under `src/utils` or `src/collectors` (only the canonicalizer, text cleaner, dedupe, and RSS collectors remain).【F:AGENTS.md†L9-L27】【9ef1df†L1-L2】【078f06†L1-L2】
- Configuration guidance claims `config/` stores YAML per environment and calls out `config/rate_limits.yaml` and `config/features.yaml`, but the repository only ships Python modules plus `config.toml`; there are no YAML counterparts.【F:AGENTS.md†L24-L27】【F:AGENTS.md†L120-L137】【F:AGENTS.md†L183-L187】【9c3c76†L1-L2】【9bcd19†L1-L1】【a27d55†L1-L1】
- The local development examples suggest `python run_collector.py --sources config/sources.yaml`, while the CLI actually expects one or more source IDs (the command fails if given a path).【F:AGENTS.md†L132-L137】【F:run_collector.py†L300-L336】
- **Impact:** Maintainers following AGENTS.md will look for non-existent YAML configs, misname feature-flag files, or run the collector with invalid arguments.
- **Proposed patch:**
  - Update the pipeline diagram to reference the real modules (e.g., `[collectors] → [utils.text_cleaner] → [utils.dedupe] → …`).
  - Replace YAML mentions with `config.toml`/`config/settings.py`, and clarify that feature flags are currently unmanaged (or document the intended path once implemented).
  - Correct the sample command to `python run_collector.py --sources nature science` (or similar ID examples) and add a note about `--sources` semantics.

### 3. `docs/faq.md` points to missing YAML configs and tooling
- Troubleshooting guidance directs operators to `config/sources.yaml`, `config/rate_limits.yaml`, and `config/enrichment.yaml`, none of which exist; rate limiting and enrichment live under `config.toml` and Python helpers instead.【F:docs/faq.md†L15-L28】【9c3c76†L1-L2】【9bcd19†L1-L1】
- The FAQ also instructs running `python scripts/rate_limit_probe.py`, but no such script is shipped in `scripts/` (or anywhere else).【F:docs/faq.md†L15-L21】【a1a1ce†L1-L1】
- **Impact:** On-call responders are sent to dead paths and tooling, wasting time during incidents.
- **Proposed patch:** revise the FAQ to point at `config.toml` (e.g., `rate_limiting` section) and `config/sources.py`, describe how to adjust per-source throttling via `make config-set`/`noticiencias.config_manager`, and replace the missing probe script with available diagnostics (e.g., `run_collector.py --dry-run --sources <id>` plus log inspection).

## Open Questions
- **Feature flags:** `AGENTS.md` assumes a `config/features.yaml`, but no replacement exists. Missing: confirm whether feature flags moved elsewhere or are yet to be implemented.
