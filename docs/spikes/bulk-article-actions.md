# Bulk article actions — spike investigation note (plan 017)

> **Status**: SPIKE COMPLETE. The UI slice is now SHIPPED with the
> divergence-bug fix. The `run_bulk` helper, `reset_one_article` per-item
> action, and their tests are the reusable deliverables. Production use
> above the 5-article cap still requires a queue/async approach.

## What one Despublicar does (per row)

**Handler**: `apps/refinery/main.py:782` → `delete_article(target)`.

1. **Clone the target repo** (`main.py:795-797`): `shutil.rmtree(TARGET_DIR)` then `git_handler.clone_repo()`. Fresh clone every time.
2. **Find the article** (`main.py:805-816`): search `src/content/posts/` by `refinery_id` or `file_name`.
3. **Create a branch** (`main.py:828-830`): `git_handler.create_branch(target_repo_obj, branch_prefix="delete/article")`.
4. **Delete the file + prune manifest + prune hero allowlist + append route smoke check** (`main.py:832-861`): `target_file.unlink()`, `prune_refinery_manifest_for_post()`, `prune_hero_placeholder_allowlist_for_post()`, `append_deleted_route_smoke_check()`.
5. **Commit & push** (`main.py:864-866`): `git_handler.commit_and_push()`.
6. **Create a Pull Request** (`main.py:868-880`): `git_handler.create_pull_request()`.

**Cost**: 1 fresh clone + 1 branch + 1 commit + 1 push + 1 PR = **~5-15 seconds per article** (network-bound). Each Despublicar opens a **separate GitHub PR**.

## What one Reset does (per row)

**Handler**: `apps/refinery/admin_panel.py:2759-2828` (inline in the published-content tab).

1. **Clone or pull the target repo** (`admin_panel.py:2764-2778`): if `TARGET_DIR` exists, `repo.remotes.origin.pull()`; if pull fails, `shutil.rmtree()` + fresh clone.
2. **Find the article** (`admin_panel.py:2780-2800`): search `src/content/posts/` by `refinery_id` or `file_name`.
3. **Remove from git index + unlink file** (`admin_panel.py:2802-2812`): `repo.index.remove()`, `target_article.file_path.unlink()`.
4. **Commit + push** (`admin_panel.py:2813-2816`): single `repo.index.commit()` + `repo.remotes.origin.push()`.
5. **Delete from DB** (`admin_panel.py:2818-2826`): `db_manager.delete_article(refinery_id)` + `db_manager.delete_article(refinery_id + ".md")`.

**Cost**: 1 pull (or clone) + 1 index.remove + 1 unlink + 1 commit + 1 push = **~3-10 seconds per article** (network-bound). Reset pushes directly to the target branch (no PR).

## Key difference

- **Despublicar** = opens a PR (review-gated deletion)
- **Reset** = pushes directly to the target branch (immediate deletion, no review)

## Partial-failure semantics (the divergence bug — FIXED)

The original `advisor/017-*` branch wired a synchronous batch that called
`_reset_one_local` in a loop, then a single batched `commit` + `origin.push()`
for the whole run. This had a **divergence bug**:

1. **Continue-on-error meant an item that raised at `unlink` had already
   lost its DB rows** (deleted at step 2) yet was reported "failed" — DB
   says deleted, filesystem says deleted, but git index still has the file.
2. **If the final single `push` failed, every "succeeded" item was locally
   deleted** but still live in the remote.

**Fix (shipped):** the shipped bulk action uses three pieces:

- **`apps/refinery/bulk_helper.py` (`run_bulk`)** — a pure helper that
  runs a per-item callable with continue-on-error + batch cap. It never
  touches DB/git/filesystem itself; the caller's action owns the lifecycle.
- **`apps/refinery/published_content.py` (`reset_one_article`)** — the
  per-item action that does: `index.remove` → `unlink` → `commit` →
  `push` → `delete DB rows`. **DB rows are only deleted *after* the push
  succeeds.** If any step before the DB delete raises, the DB rows
  remain intact and the article can be retried.
- **`admin_panel.py` bulk-action UI** — multi-select + confirmation
  checkbox + `op_in_progress` double-submit guard + progress bar +
  structured per-item success/failure report. Batch cap is 5.

If item 7 of a 5-item batch fails at `push`, items 1-6 are already
committed and pushed (remote is in sync); item 7's DB rows were never
touched (the push failed before the DB delete); the report shows 6
succeeded, 1 failed with reason.

## Batch cap

Given ~3-15 seconds per article (network-bound), a synchronous Streamlit loop of:
- **5 articles** = 15-75 seconds (acceptable with a progress bar)
- **10 articles** = 30-150 seconds (borderline — Streamlit rerun timeout risk)
- **20+ articles** = 60-300+ seconds (unacceptable synchronous — needs a queue)

**Recommended cap**: 5 articles per batch for the synchronous slice. Beyond that, the note recommends a queue/async approach (the spike's STOP condition).

## Auth

The existing destructive "Reset Total" flow (`admin_panel.py:1781-1800`) uses a **confirmation checkbox** + `disabled=not confirm_delete`. The per-row Despublicar/Reset buttons have **no auth gate** beyond the Refinery session login (`st.session_state.get("refinery_ui_authenticated")`). The bulk action should reuse the same confirmation-checkbox pattern as Reset Total.

## Streamlit rerun safety

The `op_in_progress` session flag pattern (`admin_panel.py:720,722,750`) disables buttons during an operation to prevent double-submit. The bulk action must set `st.session_state["op_in_progress"] = True` before the loop and `False` after, and disable the bulk-action button while in progress.

## Recommendation

- **The synchronous UI slice is SHIPPED** with the divergence-bug fix
  (per-item commit/push, DB rows only deleted after push succeeds).
  The batch cap is 5 articles.
- **`run_bulk` helper is reusable** — pure, testable, no Streamlit/git/DB
  dependencies. Can be reused for future batch actions (e.g., bulk
  despublicar).
- **For production batches > 5 articles**: implement a queue-based
  approach (background task + status file/websocket). This is a separate
  plan, not part of this spike.
- **Extending to Despublicar**: possible, but Despublicar (PR-based) is
  slower than Reset (direct push), so the cap should be lower (3 articles).
