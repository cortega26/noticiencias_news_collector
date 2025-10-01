# noticiencias_news_collector — Codex‑Optimized E2E Audit Prompts

These are **copy‑paste prompts** tuned for ChatGPT **Codex** (container/agent) to run an **end‑to‑end audit** of this repo.

> **How to use**
>
> 1) Open the repo in Codex.  
> 2) Paste one prompt at a time.  
> 3) Allow safe commands (read‑only, lint, tests). For changes, request **unified diffs** you can apply locally (`patch -p0 < file.patch`) instead of blind edits.  
> 4) Prefer **recorded fixtures** over live web requests.

> **Conventions for all prompts (Codex must follow):**
>
> - **Never hit external sites unless explicitly instructed.** If unavoidable, propose a **mock/fixture** plan first (e.g., VCR.py).  
> - Output **tables** in Markdown. Output code changes as **unified diff** blocks.  
> - Keep a **findings → fix** mapping (“issue | impact | exact fix | file/line”).  
> - Suggest **PR‑ready commits** with conventional messages (e.g., `fix(scraper): ...`).  
> - Assume Python ≥3.10. Prefer `uv` (or `pip-tools`) if detected.  
> - Respect **fast, cacheable installs**. Avoid `sudo`. Use timeouts on network I/O.  
> - If a tool is missing, propose the exact add (dev dependency + config + CI step).

---

## 0) Orchestrator (run first)

**Prompt:**  
“Act as a senior Python engineer performing an **end‑to‑end audit**.  
Tasks: (1) inventory the repo, (2) detect Python/tooling, (3) build a minimal local run path, (4) produce a **phase plan** that calls Prompts 1–10 below in optimal order, with clear stop criteria and artifacts per phase.  
Deliver:  

- table: *area | current state | risk | priority | artifact to produce*  
- `make help` plan or task list (targets + one‑liners)  
- a minimal ‘bootstrap’ (one command) and a full ‘dev up’ (≤3 commands)  
- Do **not** modify code yet; only propose diffs.”

---

## 1) Repo & Environment Health

**Prompt:**  
“Audit repository structure and environment. Check: `pyproject.toml`/`requirements*`, Python version, entry points, CLI, packaging, and `.gitignore`.  
Deliver:  

- risk table *(area | risk | impact | fix)*  
- minimal deterministic setup (one command), plus a **`Makefile` with targets**: `bootstrap`, `lint`, `typecheck`, `test`, `e2e`, `perf`, `security`, `clean`.  
- unified diffs to: pin deps, add lock/constraints, normalize layout, and add `ruff`, `mypy`, `pytest` config.”

---

## 2) Dependency & Supply‑Chain Security

**Prompt:**  
“Run static & supply‑chain scans. Tools: `pip-audit`/`safety`, `bandit`, secret scanners (`gitleaks`/`trufflehog`).  
Deliver:  

- table *(package/file | vuln/secret | severity | exploit path | fix)*  
- diffs to add scanners as dev‑deps + config files + **CI jobs** (GitHub Actions).  
- If any CVEs found: propose safe version bumps with notes on compatibility and test gates.”

---

## 3) Data Sources, Scrapers & Compliance

**Prompt:**  
“Map all **data sources** and **scrapers**. Verify **ToS/robots.txt** friendliness, throttling, retries/backoff, ETag/If‑Modified‑Since caching, deduping, and Cloudflare/Imperva failure modes.  
Deliver:  

- matrix *(source | auth? | ToS constraints | throttle | cache | failure mode | fallback | fix)*  
- diffs to add: user‑agent strategy, timeouts, exponential backoff, circuit‑breaker, and **no‑live** tests using VCR.py/fixtures.”

---

## 4) Pipeline E2E & Data Integrity

**Prompt:**  
“Trace: **acquire → parse → normalize → store → score → output**. Add **schema contracts** with `pydantic`/TypedDict. Validate timestamps/timezones, duplicates, nulls, and score invariants (non‑negative, stable).  
Deliver:  

- a **single E2E test** (CI‑safe, offline via fixtures)  
- field‑level validation with actionable messages  
- reconciliation report *(expected vs actual)*  
- diffs for contracts + validations + failing→passing tests.”

---

## 5) Scoring Logic: Correctness & Metrics

**Prompt:**  
“Audit the **news scoring** algorithm. Identify features/weights and sensitivity. Define KPIs: `precision@K`, coverage, recency, diversity.  
Deliver:  

- a tiny **golden dataset** and **golden tests**  
- a CLI/notebook that prints per‑release deltas  
- diffs to remove magic numbers, reduce branching, and add threshold guards to prevent regressions.”

---

## 6) Performance & Scalability

**Prompt:**  
“Profile hot paths (network, parsing, scoring). Measure wall time, CPU, memory, I/O, and **request counts** on a representative workload.  
Deliver:  

- table *(step | baseline | optimized | Δ%)*  
- diffs: batching, streaming parsers, async where safe, memoization/caching by URL/content hash  
- **performance budget** (max runtime, max requests, peak RAM) enforced via CI perf test.”

---

## 7) Error Handling, Logging & Observability

**Prompt:**  
“Unify error handling and logging. Replace prints with **structured logs** (JSON) containing correlation IDs, source URL, retry count, and latency.  
Deliver:  

- logging spec + sample log lines  
- diffs: logger setup, error taxonomy (recoverable/fatal), healthcheck command, and minimal metrics (counters/timers)  
- a lightweight **runbook**: common failures → diagnosis → resolution.”

---

## 8) CI/CD & Reproducibility

**Prompt:**  
“Create/upgrade GitHub Actions to run: lint, type‑check, unit/E2E (offline fixtures), perf budget, security scans. Enable dependency caching and upload artifacts (coverage, perf, test logs). Optional: containerize with a minimal non‑root image and publish on tags.  
Deliver:  

- CI YAML (full) + status badges for README  
- diffs for Dockerfile (if applicable) and Make targets  
- target: **green CI from clean clone to artifacts ≤10 min**.”

---

## 9) Documentation & DevEx

**Prompt:**  
“Revamp docs to speed adoption.  
Deliver:  

- `README` (what/why/how/limits) + **Quickstart (≤3 commands)**  
- architecture diagram (Mermaid) + data contracts  
- troubleshooting & FAQ  
- `CONTRIBUTING.md` (style, lint, types, tests, commit conv.)  
- `CHANGELOG.md` with the audit outputs.”

---

## 10) Release Candidate Dry‑Run

**Prompt:**  
“Produce a **release candidate** from the audit branch.  
Deliver:  

- `version` bump proposal + `CHANGELOG` entry  
- tag + GH release draft notes (highlights, breaking changes)  
- optional: container image build/run instructions  
- a final **checklist** asserting: green CI, perf budget met, zero high‑sev vulns, docs updated, reproducible bootstrap.”

---

### Standard Output Formats (Codex must use)

- **Findings table:** `issue | impact | evidence | exact fix | file:line`  
- **Unified diff blocks** for all code/config changes.  
- **Command blocks** to reproduce: setup, run, test, measure.  
- **PR plan:** ordered commits with messages and scope.

### Safety & Offline‑first

- Prefer **fixtures** (VCR.py) over real web calls. If live access is indispensable, ask for permission and provide: target host, rate limits, headers, and failure‑recovery plan.

---

**Tip:** Start with **Prompt 0 → 1 → 8**, then branch into 2–7 in parallel, and finish with 9–10.
