# Spec: Decompose RefineryEngine into Focused Collaborators

Status: Active  
Scope: `news_collector/logic/workflows/refinery_engine.py`  
Authority: Constrained by `docs/AGENTS.md`, `docs/ARCHITECTURE.md`, `docs/SOURCE_OF_TRUTH.md`

---

## 1. Goals

`RefineryEngine` currently owns six distinct concerns inside a single 1 250-line class:

| Concern | Lines / methods |
|---|---|
| Canonical publication identity | `process_single_article` Priority 1/2/3 block, `_extract_slug`, collision loop |
| Image handling | `_download_image`, `_derive_image_slug`, `_queue_image_brief`, `_resolve_brief_image` |
| Target-repo file I/O + manifest | `_find_existing_file`, `_load_manifest`, `_update_manifest` |
| PR / Git orchestration | `_attempt_publishing_recovery`, `_resolve_repo_url`, PR creation + DB mark blocks |
| Editorial policy enforcement | `_enforce_editorial_policy`, `_log_enforcement_decision` |
| Audit scheduling | `_schedule_optional_audit`, `_record_audit_status` |

The backlog item from `docs/dev/source-of-truth-backlog.md` says:

> Extract focused collaborators for **publication identity**, **target-repo writes**,
> **image-brief handling**, and **PR orchestration**.

This spec covers exactly those four collaborators. Policy enforcement and audit scheduling are acknowledged debt but are **out of scope** for this task (they require a dedicated editorial module redesign).

**Goals:**

1. Extract four collaborators with single, testable responsibilities.
2. `RefineryEngine.__init__` signature stays identical — no call-site changes.
3. All 13 test files that import `RefineryEngine` continue to pass without modification.
4. Each collaborator can be instantiated and unit-tested without `RefineryEngine`.
5. The full article publication path produces identical outputs before and after.

---

## 2. Current Problems

### 2.1 Testability

`_download_image`, `_find_existing_file`, and canonical identity logic cannot be tested independently without constructing a full `RefineryEngine` with `EditorAgent`, `GitHubPublisher`, `DatabaseManager`, and `config`. Each test that touches one of these internal methods must mock 4–5 unrelated dependencies.

### 2.2 Reasoning difficulty

`process_single_article` is a 200-line method that branches on image state, identity state, policy state, and PR state. Understanding any single concern requires reading past all the others.

### 2.3 LAW-B3 / LAW-B4 violations

Per `docs/AGENTS.md`:

- LAW-B3: orchestration and decision logic must stay separate.
- LAW-B4: I/O must stay at the edges.

Image HTTP I/O (`_download_image`) and file-system I/O (`_update_manifest`, target file write) currently live inside an orchestration class that also does editorial AI calls and Git operations.

### 2.4 PR body duplication

`process_single_article` and `_attempt_publishing_recovery` both build the same PR body string. This is a refactor trigger per LAW-B3 section of AGENTS.md.

---

## 3. Proposed Collaborators

### 3.1 `PublicationIdentityResolver`

**File:** `news_collector/logic/workflows/publication_identity.py`  
**Owns:** Everything about *determining* the canonical slug, date, and filename for an article — before any I/O is performed.

**Public interface:**

```python
@dataclass
class PublicationIdentity:
    final_slug: str         # e.g. "2024-01-25-my-article"
    canonical_date: str     # e.g. "2024-01-25"
    output_filename: str    # e.g. "2024-01-25-my-article.md"
    is_new: bool            # True = creation mode; False = recovered from DB or FS

class PublicationIdentityResolver:
    def __init__(self, db, manifest: "PublicationManifest"):
        ...

    def resolve(
        self,
        article_id: str,
        article: dict,
        posts_dir: Path,
    ) -> PublicationIdentity:
        """
        Priority 1: DB canonical slug (immutable identity).
        Priority 2: FS scan via manifest (legacy recovery + self-heal).
        Priority 3: Creation mode — derive from published_date / collected_date / now.
        Collision avoidance runs only in Priority 3.
        """

    def backfill_slug(self, article_id: str, slug: str) -> None:
        """Write slug to DB. Called by resolver when Priority 2 finds an existing file."""

    def register_slug(self, article_id: str, slug: str) -> bool:
        """Write new slug to DB. Called after policy approval (B-02 / F-0018). Returns True if inserted."""

    @staticmethod
    def extract_slug(content: str, fallback_id: str) -> str:
        """
        Pure function. Extract slug from frontmatter 'slug:' or 'title:' field.
        Applies NFKD normalization, ASCII encode, sanitize, dedash.
        Replaces current RefineryEngine._extract_slug.
        """
```

**Does NOT own:** DB write lifecycle, file writes, policy decisions, image logic.

**Boundary invariants:**
- `resolve()` is read-only with respect to the DB and filesystem (no writes inside the method itself; writes happen via `backfill_slug` and `register_slug` which callers invoke explicitly).
- `extract_slug` is a pure function — no I/O.

---

### 3.2 `ArticleImageHandler`

**File:** `news_collector/logic/workflows/image_handler.py`  
**Owns:** Everything about resolving an article's image — brief lookup, HTTP download, brief queuing, and asset materialization.

**Public interface:**

```python
@dataclass
class ImageResolution:
    resolved: bool          # True = image ready in article dict
    image_url: str | None   # Local path e.g. "~/assets/images/2024-01-25-slug.jpg"
    image_alt: str | None
    queued_brief: bool      # True = no image yet, brief was queued, caller must stop publishing

class ArticleImageHandler:
    def __init__(self, image_briefs: ImageBriefStore):
        ...

    def resolve(
        self,
        *,
        article: dict,
        article_id: str,
        canonical_date: str,
        preferred_slug: str | None,
        target_dir: Path,
    ) -> ImageResolution:
        """
        1. Derive image_slug via _derive_image_slug logic.
        2. Check existing brief (editorial_image_ready / resolved).
        3. If brief ready: materialize asset, return resolved=True.
        4. If raw HTTP URL: download. On success return resolved=True.
           On failure: queue brief, return queued_brief=True.
        5. If missing or default placeholder: queue brief, return queued_brief=True.
        """

    def download(self, url: str, slug: str, target_dir: Path) -> str | None:
        """
        Download remote image. Resolve extension from Content-Type header,
        fall back to URL heuristic. Returns "~/assets/images/{slug}{ext}" or None.
        Replaces current RefineryEngine._download_image.
        """
```

**Does NOT own:** image brief business logic (that stays in `ImageBriefStore`), editorial policy, file writing for article content.

---

### 3.3 `TargetRepoWriter`

**File:** `news_collector/logic/workflows/target_repo_writer.py`  
**Owns:** Writing `.md` files to `posts_dir`, the sidecar manifest, and finding existing files.

**Public interface:**

```python
class TargetRepoWriter:
    def __init__(self):
        self._manifest_cache: dict[str, str] = {}
        self._manifest_loaded: bool = False

    def find_existing_file(self, posts_dir: Path, article_id: str) -> Path | None:
        """
        Fast: manifest cache lookup.
        Slow: linear scan for 'refinery_id: "{article_id}"' in first 50 lines.
        Self-heals manifest on slow-path hit.
        Replaces current RefineryEngine._find_existing_file.
        """

    def write_article(
        self,
        *,
        posts_dir: Path,
        output_filename: str,
        content: str,
        article_id: str,
        target_dir: Path,
    ) -> Path:
        """
        Path-traversal guard (NC-BE-015 S0).
        Writes content to posts_dir / output_filename.
        Calls update_manifest afterward.
        Returns the written Path.
        """

    def update_manifest(self, posts_dir: Path, article_id: str, filename: str) -> None:
        """
        Atomic persist (tmp + os.replace).
        Replaces current RefineryEngine._update_manifest.
        """

    def load_manifest(self, posts_dir: Path) -> None:
        """
        Load sidecar manifest into memory.
        Replaces current RefineryEngine._load_manifest.
        """
```

**Does NOT own:** Git operations, DB writes, policy checks.

**Boundary invariant:** `write_article` raises `ValueError` (not silently returns False) if path traversal is detected — callers get an explicit error rather than a silent skip.

---

### 3.4 `PROrchestrator`

**File:** `news_collector/logic/workflows/pr_orchestrator.py`  
**Owns:** Creating GitHub pull requests, recovering articles stuck in `publishing` state, marking articles as published in the DB.

**Public interface:**

```python
@dataclass
class PRResult:
    pr_url: str | None
    recovered: bool = False   # True if returned via publishing-state recovery

class PROrchestrator:
    def __init__(self, git: GitHubPublisher, db, config):
        ...

    def create_pr(
        self,
        *,
        article_id: str,
        article: dict,
        branch_name: str,
        output_filename: str,
    ) -> PRResult:
        """
        Resolve repo_url from config.
        Build PR body (canonical format, no duplication).
        Call git.create_pull_request.
        On success: call db.mark_article_published.
        Returns PRResult.
        """

    def attempt_recovery(
        self,
        *,
        numeric_id: int,
        article_id: str,
        article: dict,
    ) -> PRResult | None:
        """
        B-01 / F-0012, F-0015: If article stuck in 'publishing' state, try to recover.
        Returns PRResult if recovery succeeded, None if no recovery needed.
        Replaces current RefineryEngine._attempt_publishing_recovery.
        """

    def resolve_repo_url(self) -> str | None:
        """
        Extract target_repo_url from config.
        Replaces current RefineryEngine._resolve_repo_url.
        Supports both object-attribute and dict configs for backward compat.
        """
```

**Does NOT own:** branch creation (that's `GitHubPublisher.create_branch`), file writes, policy checks.

**Boundary invariant:** PR body is built exactly once inside `create_pr`. Both the normal path and recovery path call `create_pr`, eliminating the duplication in the current code.

---

## 4. What Stays in `RefineryEngine`

After extraction, `RefineryEngine` retains:

| Responsibility | Method(s) |
|---|---|
| Batch loop | `process_articles` |
| Main orchestration flow | `process_single_article` (thinner, delegates to collaborators) |
| Policy enforcement | `_enforce_editorial_policy`, `_log_enforcement_decision` |
| Audit scheduling | `_schedule_optional_audit`, `_record_audit_status` |
| Payload normalization | `_normalize_article_payload` |
| Frontmatter validation | `_has_quoted_date_only_frontmatter` |
| Collaborator wiring | `__init__` (instantiates all four collaborators) |

`__init__` constructs collaborators and wires them together. Existing tests that mock `RefineryEngine` at the class boundary are unaffected.

---

## 5. Migration Strategy

### 5.1 Backward compatibility

- `RefineryEngine.__init__` signature is **unchanged**.
- All four new modules are imported inside `RefineryEngine.__init__` (or at module top) and composed there.
- No external callers need to know about the collaborators unless they want to test them directly.
- The collaborator classes are public (no leading underscore) so they can be imported independently in tests.

### 5.2 Migration sequence (matches todo.md)

1. Create `publication_identity.py` with `PublicationIdentityResolver` and `PublicationIdentity`.  
   - Wire into `RefineryEngine` — replace Priority 1/2/3 block + `_extract_slug`.  
   - Run full test suite. All existing tests must pass.

2. Create `target_repo_writer.py` with `TargetRepoWriter`.  
   - Wire into `RefineryEngine` — replace manifest methods and the `write_text` + `_update_manifest` call.  
   - Run full test suite.

3. Create `image_handler.py` with `ArticleImageHandler`.  
   - Wire into `RefineryEngine` — replace image resolution block.  
   - Run full test suite.

4. Create `pr_orchestrator.py` with `PROrchestrator`.  
   - Wire into `RefineryEngine` — replace PR creation block and `_attempt_publishing_recovery`.  
   - Run full test suite.

5. After all four collaborators are wired, remove the corresponding private methods from `RefineryEngine` (they are now dead code).

6. Run the decompose_refinery e2e test suite to confirm all collaborator tests pass.

### 5.3 Branch strategy

Each collaborator extraction is a separate atomic commit. The commit message format is:

```
refactor(refinery): extract <CollaboratorName> from RefineryEngine

- Moves: <list of methods moved>
- RefineryEngine delegates to new collaborator
- Existing tests unchanged
```

---

## 6. Verification Strategy

### 6.1 Regression gate (existing tests must not break)

Run after each step:

```bash
make lint
make type
make test
```

All 13 test files that currently import `RefineryEngine` must pass with zero changes.

### 6.2 Collaborator unit tests (`tests/decompose_refinery/`)

Each collaborator has its own test file proving it works **without** constructing a `RefineryEngine`:

| File | What it proves |
|---|---|
| `test_publication_identity.py` | Priority 1/2/3 slug resolution, extract_slug purity, collision avoidance, self-heal backfill |
| `test_target_repo_writer.py` | Manifest CRUD, atomic write, fast-path lookup, slow-path scan, path-traversal guard |
| `test_image_handler.py` | HTTP download, Content-Type extension detection, brief queuing, brief materialization |
| `test_pr_orchestrator.py` | PR body construction, repo_url resolution, publishing-state recovery, mark_published call |
| `test_engine_regression.py` | Full pipeline (article in → PR out) with all collaborators wired — proves no behaviour change |

### 6.3 Specific invariants verified per test file

#### `test_publication_identity.py`

- **IDENT-01**: DB slug present → `is_new=False`, slug and date extracted from DB value, no FS scan.
- **IDENT-02**: DB empty, file exists in FS matching `refinery_id` → `is_new=False`, manifest self-healed.
- **IDENT-03**: DB empty, no FS file, `published_date` present → `is_new=True`, date from source.
- **IDENT-04**: DB empty, no FS file, no `published_date`, `collected_date` present → `is_new=True`, date from collected.
- **IDENT-05**: DB empty, no FS file, no dates → `is_new=True`, date from `datetime.now()` (current-date fallback, documented as known debt per backlog).
- **IDENT-06**: Collision → suffix counter appended until unique.
- **IDENT-07**: `extract_slug` path traversal test cases (from existing `test_refinery_slug_security.py` — must all still pass against the static method).
- **IDENT-08**: `extract_slug` Unicode normalization.

#### `test_target_repo_writer.py`

- **WRITE-01**: `write_article` creates the file with correct content.
- **WRITE-02**: `write_article` calls `update_manifest` after writing.
- **WRITE-03**: `update_manifest` uses atomic tmp+replace (no `.tmp` left behind).
- **WRITE-04**: `find_existing_file` returns manifest hit when file exists.
- **WRITE-05**: `find_existing_file` falls back to slow scan on stale manifest entry.
- **WRITE-06**: `find_existing_file` self-heals manifest on slow-path hit.
- **WRITE-07**: `write_article` raises `ValueError` on path traversal attempt.

#### `test_image_handler.py`

- **IMG-01**: `download` saves file with Content-Type-derived extension.
- **IMG-02**: `download` falls back to URL heuristic when Content-Type unknown.
- **IMG-03**: `download` returns None on HTTP error (no crash).
- **IMG-04**: `resolve` with existing brief in `editorial_image_ready` status → `resolved=True`, asset materialized.
- **IMG-05**: `resolve` with HTTP URL → download called, `resolved=True`.
- **IMG-06**: `resolve` with HTTP URL download failure → `queued_brief=True`, `resolved=False`.
- **IMG-07**: `resolve` with no URL → `queued_brief=True`, `resolved=False`.
- **IMG-08**: `resolve` with default placeholder URL → `queued_brief=True`, `resolved=False`.

#### `test_pr_orchestrator.py`

- **PR-01**: `create_pr` calls `git.create_pull_request` with correct repo_url.
- **PR-02**: `create_pr` calls `db.mark_article_published` on success.
- **PR-03**: `create_pr` returns `PRResult(pr_url=None)` when git call fails.
- **PR-04**: `resolve_repo_url` reads from `config.github.target_repo_url` (object).
- **PR-05**: `resolve_repo_url` reads from `config.github["target_repo_url"]` (dict).
- **PR-06**: `resolve_repo_url` reads from `config.target_repo_url` (legacy flat).
- **PR-07**: `attempt_recovery` returns None when article not in publishing state.
- **PR-08**: `attempt_recovery` returns None when publishing timeout exceeded.
- **PR-09**: `attempt_recovery` returns PRResult on successful recovery PR creation.
- **PR-10**: PR body contains article_id, source_id, source_name (no raw format drift).

#### `test_engine_regression.py`

- **E2E-01**: Article with HTTP image → PR created, file written to posts_dir, manifest updated, DB marked published. All collaborators exercised end-to-end via mocked I/O boundaries.
- **E2E-02**: Article already published (DB slug present) → re-process reuses identical filename, no duplicate file.
- **E2E-03**: Article stuck in publishing state → recovery path returns True.
- **E2E-04**: Article with failing image download → `process_single_article` returns False, no file written.
- **E2E-05**: Article rejected by editorial policy (score below threshold) → returns False before file write.

---

## 7. Out of Scope

The following are acknowledged debt but are **not** part of this task:

- **Remove current-date fallback** from canonical identity (tracked in backlog as "high" priority). The current-date fallback in IDENT-05 is preserved and documented — fixing it requires an editorial workflow change.
- **Editorial policy enforcement extraction** (`_enforce_editorial_policy`, `_log_enforcement_decision`) — these should eventually move to a dedicated policy module, but that touches `EditorialPolicy` and requires a separate spec.
- **Audit scheduling extraction** (`_schedule_optional_audit`, `_record_audit_status`) — same reasoning.
- **Retire duplicate collector entrypoints** — separate backlog item.
- **Cross-repo contract gate** — separate spec.
