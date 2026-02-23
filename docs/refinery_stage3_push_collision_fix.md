# Refinery Stage 3 Push Collision Fix

## Summary

Stage 3 now handles deterministic branch collisions (`content/update-<slug>`) without force-pushing.

## Behavior

1. Before branch operations, the publisher runs `git fetch origin --prune`.
2. If `origin/<branch>` exists, local checkout is reset to the remote tip (`checkout -B`) and rebased to ensure it is current.
3. If `origin/<branch>` does not exist, branch creation is reset to the deterministic base ref `origin/<base_branch>` (default: `origin/main`).
4. Push flow:
   - First attempt: `git push origin <branch>`.
   - If rejected as non-fast-forward: fetch, rebase onto `origin/<branch>`, retry push once.
5. If rebase conflicts:
   - Rebase is aborted.
   - Stage fails with a clear error including branch name and conflicting file list.
   - No force push is attempted.
6. If there are no local changes, commit/push is skipped (idempotent reruns).
7. Stage 3 ordering is enforced as branch sync first, then content write/manifest update, then commit/push.

## Invariants

- Remote history is never rewritten.
- Force push is never used.
- At most one non-fast-forward rebase retry occurs per push attempt.
- When `origin/<branch>` is absent, branch base is deterministic (`origin/main` by default).
- Cleanup on failure is enforced in `finally`-backed guards for branch setup and commit/push paths.
- Pipeline exits cleanly in all failure paths (rebase/merge/cherry-pick/revert states are aborted, in-progress markers are checked, and working tree cleanliness is verified).
- Base branch source is centralized in `GitHubPublisher` (`base_branch` constructor arg, default `DEFAULT_BASE_BRANCH`).
- Branch synchronization completes before any Stage 3 content file write.
- Interactive prompts are disabled for git auth/operations (`GIT_TERMINAL_PROMPT=0` + askpass).
