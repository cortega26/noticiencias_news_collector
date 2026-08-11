# Plan 041 — Check matrix (Step 1 inventory)

Every workflow job / Make / npm target, with trigger, command, and canonical owner.

## Backend (noticiencias_news_collector)

| Check | Make target | CI workflow | Trigger | Canonical owner | Notes |
|---|---|---|---|---|---|
| Bootstrap | `make bootstrap` | — | manual | `bootstrap` | Provisioning only |
| Lint | `make lint` | `ci.yml` (lint job) | push/PR | `lint` | Ruff+Black+isort |
| Type | `make type` | `ci.yml` (type job) | push/PR | `type` | mypy strict |
| Unit test | `make test` | `ci.yml` (test job) | push/PR | `test` | fast, excludes e2e |
| Full test | `make test-all` | — | manual/prepush | `test-all` | includes slow e2e |
| Coverage | `make check-coverage` | `ci.yml` (coverage job) | push/PR | `check-coverage` | ≥80% |
| Contracts | `make test-contracts` | `verify-ci` (no dedicated ci.yml job; coverage gate ≥80% on news_collector/contracts) | push/PR | `test-contracts` | D1 contract enforcement |
| Boundaries | `make test-boundaries` | `verify-ci` (no dedicated ci.yml job) | push/PR | `test-boundaries` | D1 system boundary |
| System | `make test-system` | `system-verification.yml` | push/PR | `test-system` | S1 scoped |
| Security | `make security` | `quality.yml` (quality-gate job) | push/PR + scheduled | `security` | supply-chain + bandit + gitleaks secret scan |
| Build | `make build` | `release.yml` | release | `build` | wheel artifact |
| Config docs | `make config-docs-check` | `ci.yml` (config job) | push/PR | `config-docs-check` | schema/docs parity |
| Quality gate | `make quality-gate` | `quality.yml` | push/PR | `quality-gate` | snapshot-first |
| Prepush | `make prepush` | — | manual | `prepush` | test-all + quality-gate |
| Perf | `make perf` | — | manual | `perf` | performance-marked tests |
| Mutation | — | `mutation.yml` | nightly | (retained) | scheduled diagnostic |
| Live source | — | `live-source-drift.yml` | scheduled | (retained) | scheduled diagnostic |
| Daily collector | — | `daily_collector.yml` | scheduled | (retained) | scheduled diagnostic |
| Audit inventory | — | `audit-inventory-weekly.yml` | weekly | (retained) | scheduled diagnostic |
| Placeholder audit | `make audit-todos-check` | `placeholder-audit-pr.yml` | PR | (retained) | PR-scoped SARIF |
| Docs | — | `docs.yml` | push to main | (retained) | docs build/publish |
| E2E | — | `e2e.yml` | manual | (retained) | integration e2e |
| Publication smoke | — | `publication-smoke.yml` | manual | (retained) | publication path smoke |
| Dependency lock | — | `dependency-lock-check.yml` | push/PR | (retained, but consolidate setup) | lock file checks |
| Source reliability | — | `source_reliability.yml` | scheduled | (retained) | scheduled diagnostic |
| Sync master | — | `sync-master.yml` | manual | (retained) | master sync |
| Release | — | `release.yml` | release | (retained) | release publish |

### Backend canonical `verify-ci` composition

```
verify-ci: lint type test test-contracts test-boundaries security config-docs-check
```

Excludes: `test-all` (slow e2e), `quality-gate` (LLM snapshots), `build` (release-only), `perf` (manual), scheduled diagnostics.

## Frontend (noticiencias)

| Check | npm script | CI workflow | Trigger | Canonical owner | Notes |
|---|---|---|---|---|---|
| Lint | `npm run lint` | `content-guard.yml` (validate job) | push/PR | `lint` | ESLint+Prettier+checks |
| Validate content | `npm run validate:content` | `content-guard.yml` (validate job) | push/PR | `validate:content` | frontmatter+types+freeze |
| Build | `npm run build` | `content-guard.yml` (build job) | PR | `build` | astro build |
| Dist sanity | `npm run test:dist` | `content-guard.yml` (build job) | PR | `test:dist` | dist sanity |
| Unit (vitest) | `npm run test:audit` | `content-guard.yml` (build job) | PR | `test:audit` | vitest run |
| Coverage | `npm run test:coverage` | `content-guard.yml` (build job) | PR | `test:coverage` | vitest --coverage |
| Browser (e2e) | `npm run test:e2e` | `content-guard.yml` (build job) | PR | `test:e2e` | Playwright local build |
| Contract sync | `npm run check:contract-sync` | `content-guard.yml` (validate job) | push/PR | `check:contract-sync` | cross-repo schema parity |
| Search budget | `node scripts/check-search-budget.js` | (not in CI yet) | — | (add to verify:ci) | plan 039 |
| Deploy | — | `deploy.yml` | release | (retained) | deployment |
| Deploy worker | — | `deploy-worker.yml` | release | (retained) | worker deployment |
| Continuous monitor | — | `continuous-monitor.yml` | scheduled | (retained) | scheduled diagnostic |
| Generate metrics | — | `generate-metrics.yml` | scheduled | (retained) | scheduled diagnostic |
| Image delivery quota | — | `image-delivery-quota.yml` | scheduled | (retained) | scheduled diagnostic |
| Perf monitor | — | `perf-monitor.yml` | scheduled | (retained) | scheduled diagnostic |
| Staleness alert | — | `staleness-alert.yml` | scheduled | (retained) | scheduled diagnostic |
| Sync contract snapshot | — | `sync-contract-snapshot.yml` | scheduled | (retained) | scheduled diagnostic |
| Sync image derivatives | — | `sync-image-derivatives-manifest.yml` | scheduled | (retained) | scheduled diagnostic |

### Frontend canonical `verify:ci` composition

```json
"verify:ci": "npm run lint && npm run validate:content && npm run build && npm run test:dist && npm run test:audit && CI=1 npm run test:e2e && npm run check:contract-sync"
```

Excludes: `test:coverage` (redundant with test:audit for CI gating), `deploy`, scheduled diagnostics.
