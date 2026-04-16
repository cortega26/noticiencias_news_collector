# Todo: Decompose RefineryEngine

Tracks the extraction of four focused collaborators from `RefineryEngine`.  
Consult `spec.md` before every change.  
Run `make lint && make type && make test` after each ✅ step.

---

## Phase 0 — Baseline

- [x] Read `spec.md` fully
- [x] Read `news_collector/logic/workflows/refinery_engine.py` fully
- [x] Confirm existing test suite passes as-is
  - Command: `make test`
  - Gate: all tests green before any code change
- [x] Create `tests/decompose_refinery/` with initial failing tests (see spec §6)
  - Baseline confirmed: 6 E2E tests pass, 4 wiring tests fail, 4 module files fail with ImportError

---

## Phase 1 — Extract `PublicationIdentityResolver`

File: `news_collector/logic/workflows/publication_identity.py`

- [x] **1.1** Create `PublicationIdentity` dataclass (`final_slug`, `canonical_date`, `output_filename`, `is_new`)
- [x] **1.2** Create `PublicationIdentityResolver.__init__(self, db, manifest)`
- [x] **1.3** Implement `extract_slug(content, fallback_id)` as `@staticmethod` — exact copy of current `RefineryEngine._extract_slug` logic
- [x] **1.4** Implement `resolve(article_id, article, posts_dir) -> PublicationIdentity`
  - Sub-task: Priority 1 — DB canonical slug branch
  - Sub-task: Priority 2 — FS scan via manifest, self-heal backfill
  - Sub-task: Priority 3 — creation mode (source date / collected date / now)
  - Sub-task: Collision avoidance loop (Priority 3 only)
- [x] **1.5** Implement `backfill_slug(article_id, slug)` — calls `db.set_canonical_slug`
- [x] **1.6** Implement `register_slug(article_id, slug) -> bool` — calls `db.set_canonical_slug`, returns bool
- [x] **1.7** Wire into `RefineryEngine.__init__`: instantiate `PublicationIdentityResolver(self.db, self._writer)` (writer created in Phase 2, or a temporary shim)
- [x] **1.8** Replace Priority 1/2/3 block in `process_single_article` with `self.identity_resolver.resolve(...)`
- [x] **1.9** Replace `_extract_slug` call in `process_single_article` with `PublicationIdentityResolver.extract_slug(...)`
- [x] **1.10** Delete dead private methods: `_extract_slug` from `RefineryEngine`
- [x] **1.11** Run `make test` — all existing tests green
- [x] **1.12** Run `tests/decompose_refinery/test_publication_identity.py` — IDENT-01 through IDENT-08 pass

---

## Phase 2 — Extract `TargetRepoWriter`

File: `news_collector/logic/workflows/target_repo_writer.py`

- [x] **2.1** Create `TargetRepoWriter.__init__(self)`
- [x] **2.2** Implement `load_manifest(posts_dir)` — exact copy of `_load_manifest`
- [x] **2.3** Implement `update_manifest(posts_dir, article_id, filename)` — exact copy of `_update_manifest`, atomic write
- [x] **2.4** Implement `find_existing_file(posts_dir, article_id) -> Path | None` — exact copy of `_find_existing_file`
- [x] **2.5** Implement `write_article(*, posts_dir, output_filename, content, article_id, target_dir) -> Path`
  - Sub-task: path-traversal guard (raise `ValueError` instead of `return False`)
  - Sub-task: `posts_dir.mkdir(parents=True, exist_ok=True)`
  - Sub-task: `write_text` call
  - Sub-task: call `update_manifest` after write
  - Sub-task: call `prune_hero_placeholder_allowlist_for_post`
- [x] **2.6** Wire into `RefineryEngine.__init__`: `self._writer = TargetRepoWriter()`
- [x] **2.7** Update `PublicationIdentityResolver` construction (from Phase 1) to pass `self._writer` as `manifest` argument
- [x] **2.8** Replace manifest methods in `process_single_article` with `self._writer.*`
- [x] **2.9** Replace the `target_file_path.write_text(...)` + `_update_manifest(...)` block with `self._writer.write_article(...)`
- [x] **2.10** Delete dead private methods: `_load_manifest`, `_update_manifest`, `_find_existing_file` from `RefineryEngine`
- [x] **2.11** Run `make test` — all existing tests green
- [x] **2.12** Run `tests/decompose_refinery/test_target_repo_writer.py` — WRITE-01 through WRITE-07 pass

---

## Phase 3 — Extract `ArticleImageHandler`

File: `news_collector/logic/workflows/image_handler.py`

- [x] **3.1** Create `ImageResolution` dataclass (`resolved`, `image_url`, `image_alt`, `queued_brief`)
- [x] **3.2** Create `ArticleImageHandler.__init__(self, image_briefs: ImageBriefStore)`
- [x] **3.3** Implement `download(url, slug, target_dir) -> str | None` — exact copy of `_download_image`
- [x] **3.4** Implement `resolve(*, article, article_id, canonical_date, preferred_slug, target_dir) -> ImageResolution`
  - Sub-task: `_derive_image_slug` logic (inline or small private method)
  - Sub-task: brief lookup + materialization
  - Sub-task: HTTP URL → `download()` call
  - Sub-task: download failure → queue brief
  - Sub-task: missing URL or placeholder → queue brief
- [x] **3.5** Wire into `RefineryEngine.__init__`: `self._image_handler = ArticleImageHandler(self.image_briefs)`
- [x] **3.6** Replace image resolution block in `process_single_article` with `result = self._image_handler.resolve(...)`; handle `result.queued_brief` and `result.resolved`
- [x] **3.7** Delete dead private methods: `_download_image`, `_derive_image_slug`, `_queue_image_brief`, `_resolve_brief_image` from `RefineryEngine`
- [x] **3.8** Run `make test` — all existing tests green
- [x] **3.9** Run `tests/decompose_refinery/test_image_handler.py` — IMG-01 through IMG-08 pass

---

## Phase 4 — Extract `PROrchestrator`

File: `news_collector/logic/workflows/pr_orchestrator.py`

- [x] **4.1** Create `PRResult` dataclass (`pr_url`, `recovered`)
- [x] **4.2** Create `PROrchestrator.__init__(self, git, db, config)`
- [x] **4.3** Implement `resolve_repo_url() -> str | None` — exact copy of `_resolve_repo_url`
- [x] **4.4** Implement `create_pr(*, article_id, article, branch_name, output_filename) -> PRResult`
  - Sub-task: call `resolve_repo_url()`
  - Sub-task: build PR body (single canonical implementation)
  - Sub-task: call `git.create_pull_request`
  - Sub-task: on success, call `db.mark_article_published`
- [x] **4.5** Implement `attempt_recovery(*, numeric_id, article_id, article) -> PRResult | None`
  - Sub-task: get publishing state from DB
  - Sub-task: timeout check
  - Sub-task: call `create_pr` with recovery branch
  - Sub-task: on success, call `db.mark_article_published`
- [x] **4.6** Wire into `RefineryEngine.__init__`: `self._pr_orchestrator = PROrchestrator(self.git, self.db, self.config)`
- [x] **4.7** Replace `_attempt_publishing_recovery` call in `process_single_article` with `self._pr_orchestrator.attempt_recovery(...)`
- [x] **4.8** Replace PR creation block in `process_single_article` with `self._pr_orchestrator.create_pr(...)`
- [x] **4.9** Delete dead private methods: `_attempt_publishing_recovery`, `_resolve_repo_url` from `RefineryEngine`
- [x] **4.10** Run `make test` — all existing tests green
- [x] **4.11** Run `tests/decompose_refinery/test_pr_orchestrator.py` — PR-01 through PR-10 pass

---

## Phase 5 — Final validation

- [x] **5.1** Run `tests/decompose_refinery/test_engine_regression.py` — E2E-01 through E2E-05 pass
- [x] **5.2** Run `make lint && make type && make test` — all clean
- [x] **5.3** Confirm no dead private methods remain in `RefineryEngine` (those listed in Phase 1–4 delete steps)
- [x] **5.4** Confirm `RefineryEngine.__init__` signature is unchanged
- [ ] **5.5** Call sub-agent: "review spec.md and the current implementation for gaps" — loop on feedback
- [ ] **5.6** Update this file: mark all completed tasks, note any spec deviations

---

## Deferred (not this task)

- [ ] Remove current-date fallback from canonical identity (backlog: high)
- [ ] Extract `_enforce_editorial_policy` + `_log_enforcement_decision` to policy module
- [ ] Extract audit scheduling to dedicated collaborator
- [ ] Retire duplicate collector entrypoints (`main.py` vs `scripts/run_collector.py`)
