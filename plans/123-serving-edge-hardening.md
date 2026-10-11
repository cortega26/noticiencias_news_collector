# Plan 123: Harden serving and fetch edges (bind, auth, config surface, caps)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 04016ca..HEAD -- news_collector/serving/__main__.py news_collector/serving/api.py news_collector/config/runtime.py config.toml apps/admin/src/lib/api.ts .github/workflows/daily_collector.yml news_collector/collectors/html_collector.py news_collector/collectors/rss_collector.py news_collector/logic/parsers/rss_parser.py news_collector/contracts/admin.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: none (read backend plan 099's merged result first — it
  added fail-open warnings; this plan turns two of them into enforcement.
  Plan 021's 503 fail-closed outside `development` is the floor you build on.)
- **Category**: security
- **Planned at**: commit `04016ca`, 2026-10-11
- **Issue**: omit

## Why this matters

The serving layer's auth story is "warn but serve" on dev machines and
"fail closed" elsewhere — with three holes: the dev server binds `0.0.0.0`
while `development` fails auth open (any LAN host drives
collection/publish/config endpoints with zero creds); the shipped default
`environment` is literally `"development"`, so a forgotten env var keeps
the fail-open tier; and the admin token lives in `localStorage` (any XSS
in the admin app exfiltrates a long-lived bearer). Above that, two
authenticated write surfaces lack bounds (`admin_save_config` merges an
untyped dict over full config; `admin_save_prompts` writes unbounded
payloads), the scheduled workflow carries unused write scopes, the HTML
fetch path has no byte cap (RSS has 10 MB), and feed XML parsing has no
entity-expansion guard. Each item is small; the plan sequences them so the
auth-enforcement items land first and the fetch caps ride along.

## Current state

Facts (all verified 2026-10-11):

```python
# serving/__main__.py:95 — LAN bind with acknowledged suppression
uvicorn.run(..., host="0.0.0.0",  # noqa: S104 # nosec B104 — local dev server only
```

```python
# serving/api.py:686-704 (webhook) / :738-776 (admin) — fail open in development,
# 503 outside it. Warnings added by plan 099; the `development` default is untouched.
# config/runtime.py:25 — environment: str = "development" (default)
# config.toml:2 — ships environment = "development"
# Dockerfile.serving sets NOTICIENCIAS__APP__ENVIRONMENT=production (container path pinned)
```

```ts
// apps/admin/src/lib/api.ts:44-65
const TOKEN_KEY = "refinery_admin_token";  // localStorage
export const AUTH_BYPASS: boolean =
  import.meta.env.MODE === "development" && ENV_TOKEN === null;
```

```python
# serving/api.py:1934-1998 — admin_save_config(payload: Dict[str, Any]) merges over
# full config (only secrets/sources/meta stripped at api.py:639-670), persists it.
# serving/api.py:2020-2054 — admin_save_prompts writes unbounded Dict[str, Any]
# to config/prompts.yaml (atomic write already; no size/allowlist bounds).
```

```yaml
# .github/workflows/daily_collector.yml:15-18
permissions:
  contents: write
  issues: write
# job is named `collect-and-commit` — VERIFY what it actually commits before trimming.
```

```python
# html_collector.py:359-491 — _fetch_html_conditional returns full response.text,
# no byte cap (contrast rss_collector.py:625-630 10MB ceiling).
# rss_parser.py:60-62 + rss_collector.py:740 — feedparser.parse with no
# entity-expansion/depth limits (500-entry cap at rss_parser.py:92-93 bounds
# size, not expansion factor).
```

```python
# contracts/admin.py:213-224 — AdminPublishRequest.article_url: Optional[str],
# unconstrained. NOTE: ManualIngestService.ingest (manual_ingest.py:359-371)
# already canonicalizes + validate_url_safety + host-checks — Step 4 verifies
# whether publication_run_workflow.start() reaches that synchronously (route
# already maps invalid_request→422 at api.py:1620-1644) before adding anything.
```

Repo conventions: LAW-B4 (env at config/bootstrap boundaries); serving
validates inputs explicitly and paginates deterministically; `make quality`
for security changes; `ADMIN_CORS_ORIGINS` allowlist with
`allow_credentials=False` (verified healthy — don't touch).

Prior related (do not duplicate): plan 021 (fail-closed 503s, live
verified); plan 099 (fail-open warnings — enforcement untouched per
scope); fifth-pass deferral covered HtmlCollector *follow-on SSRF*
validation — this plan does NOT re-litigate SSRF strategy routing; its
byte-cap/entity items are adjacent resource bounds, and if review finds
them inside the deferral, drop them and record it.

## Commands you will need

| Purpose   | Command                  | Provenance | Expected on success |
|-----------|--------------------------|------------|---------------------|
| Bootstrap | `make bootstrap`         | declared   | exit 0              |
| Lint      | `make lint`              | declared   | exit 0              |
| Type      | `make type`              | declared   | exit 0              |
| Unit      | `make test`              | declared   | pass                |
| Boundaries | `make test-boundaries`  | declared   | pass                |
| Quality   | `make quality`           | declared   | exit 0              |

## Scope

**In scope** (the only files you should modify):

- `news_collector/serving/__main__.py` (loopback default + explicit override)
- `news_collector/config/runtime.py` and/or bootstrap env handling
  (fail closed when environment unset/unknown — smallest change that
  achieves it; keep `development` working when EXPLICITLY set)
- `apps/admin/src/lib/api.ts` (short-lived session guidance + rotation
  docs; keep the `PUBLIC_ADMIN_API_KEY` seed and `AuthError→AuthGate` path)
- `news_collector/serving/api.py` (config allowlist + size caps; prompts
  size cap; article_url edge check ONLY if Step 4 proves it deferred)
- `.github/workflows/daily_collector.yml` (least privilege — ONLY if Step 5
  proves no step consumes write scopes)
- `news_collector/collectors/html_collector.py` (byte cap mirroring RSS)
- `news_collector/logic/parsers/rss_parser.py` (doctype/entity pre-reject)
- `tests/` for each item

**Out of scope** (do NOT touch, even though they look related):

- SSRF strategy routing for scrapling/headless/curl_cffi — fifth-pass
  deferred; do not re-litigate.
- OAuth multi-user or token-format changes — manual rotation guidance only.
- CORS origins, cookie attributes — verified healthy.
- `Dockerfile.serving` pinning — plan 130 owns it.

## Git workflow

- Branch: `advisor/123-serving-edges`
- Commit per step; e.g. `fix(serving): bind dev server to loopback by default`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Baseline + plan-099 review

Run `make lint && make type && make test-boundaries`. Read plan 099's
merged warnings so enforcement messages reuse their exact variable names.

**Verify**: gates green; warning strings known.

### Step 1: Loopback by default

Default the serving bind host to `127.0.0.1` in `__main__.py`
(keep `0.0.0.0` available via an explicit override flag/env for LAN dev
and keep the container CMD as-is). Update the `noqa`/`nosec` comment to
describe the new default.

**Verify**: default bind is loopback (start + `ss`/log probe or unit test
on the resolve function); override restores `0.0.0.0`; `make
test-boundaries` passes.

### Step 2: Fail closed on unknown environment

Require explicit `environment`: when unset/unknown, fail closed (treat as
non-development) instead of defaulting into the fail-open tier. Explicit
`development` keeps current behavior (with 099's warnings). Document token
rotation (single-key Free-style rotation needs brief pause — note it in
the admin docs touched here).

**Verify**: unset-env probe refuses admin/webhook without key (503 paths);
explicit-development probe keeps warn-and-serve; tests pin both.

### Step 3: Bound the admin write surfaces

`admin_save_config`: accept only an explicit allowlist of
operator-editable sections/keys + per-request size caps (keep
secret-stripping as-is; keep the snapshot round-trip working).
`admin_save_prompts`: same size cap + dict-shape validation. Tests for
rejected sections/oversize payloads.

**Verify**: oversize/foreign-section payloads rejected; legitimate
operator edits (snapshot round-trip) still work; `make test-boundaries` passes.

### Step 4: Verify-then-maybe-guard article_url at the edge

Read `publication_run_workflow.start()` (`publication_run_workflow.py:123-171`):
does it reach `ManualIngestService.ingest` validation synchronously
(returning `invalid_request` → the route's existing 422)? If YES: no code
change — add a regression test pinning the 422-on-bad-URL path and move
on. If NO (accepted-then-persisted-then-async-fail): add format +
`validate_url_safety` at route/`start`, mapping to 422 before enqueue.

**Verify**: bad-URL publish request yields 422 synchronously (test proves it either way).

### Step 5: Least-privilege the scheduled workflow — only if proven safe

Read ALL steps of `daily_collector.yml` (job `collect-and-commit`):
if no step commits, pushes, or opens/edits issues, reduce to
`contents: read` (and drop `issues: write`). If ANY step consumes them
(the job name suggests committing), STOP this step and record the consumer
— do not trim.

**Verify**: workflow still green in CI semantics (YAML valid; scopes documented
with an in-file comment naming the consuming step if kept).

### Step 6: Fetch resource bounds

1. HTML: content-length pre-check + streaming cap mirroring the RSS 10 MB
   policy in `_fetch_html_conditional`; over-limit → fetch failure (existing
   error handling).
2. Feeds: pre-scan rejecting bodies with doctype/entity declarations
   before `feedparser.parse` (legitimate feeds carry none); craft a fixture
   test first (investigate-first: if the pinned feedparser already limits
   expansion, record that and skip the guard).

**Verify**: over-limit page fails fast; crafted-entity fixture rejected (or
documented-unneeded); `make test` passes.

### Step 7: Full gates

Run `make lint && make type && make test && make test-boundaries && make quality`.

**Verify**: all green.

## Test plan

- Bind default + override tests; unknown-env fail-closed tests (2);
  config/prompts rejection tests (allowlist + size); article_url 422 test;
  HTML over-limit test; feed-entity fixture test.
- Existing serving/admin tests must pass unmodified (behavior for
  legitimate traffic unchanged).
- Verification: `make test-boundaries` + `make quality` green.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] Default serving bind is `127.0.0.1` (code + test)
- [ ] Unset environment fails closed (test)
- [ ] Unbounded `Dict[str, Any]` config/prompts writes rejected (tests)
- [ ] article_url bad-value → 422 synchronously (test, either pre-existing or new)
- [ ] `make lint && make type && make test && make test-boundaries && make quality` all pass
- [ ] `git diff --name-only 04016ca...HEAD` lists only the in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" doesn't match the excerpts.
- Step 4 shows validation already synchronous (good — test-only, don't add a duplicate check).
- Step 5 finds a write-scope consumer (keep scopes + comment, don't trim).
- Step 6's entity guard proves unneeded (record, don't build).
- Any item overlaps the fifth-pass SSRF deferral on review (drop that item, record it).
- Auth-flow changes break every admin call in tests (keep the seed + gate path intact per Step 0).
- A step's verification fails twice after a reasonable fix attempt.

## Maintenance notes

For the human/agent who owns this code after the change lands:

- Reviewers: every new serving endpoint must re-check these five: bind
  scope, env tier, input allowlist, size cap, request ID (see plan 129
  for the correlation-ID item).
- **Deferred:** DNS-rebinding TOCTOU in `validate_url_safety`
  (check-then-connect) — LOW-confidence investigate item (pin-IP or
  re-resolve at connect); needs connection-layer care around proxies/TLS
  SNI, unblocked by nothing but appetite.
- **Deferred:** short-lived admin sessions to replace localStorage bearer
  — rotation guidance ships here; protocol change is a separate,
  operator-approved plan.
