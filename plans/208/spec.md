# Plan 208: Keep resolved images outside the target checkout until branch setup

**Status:** DONE
**Priority:** P1
**Effort:** M
**Base:** `753ad7c3bc61ee06888ba5cb3b1e64867a0d8921` (`main`)

## Goal

Allow publication to create or reuse its article branch when image resolution
downloads or materializes a new hero image. Preserve the existing image URL,
alt text, rights provenance, editorial gates, and publication order. Do not
mutate the target Git checkout until the article branch has been selected.

## Evidence and failure being fixed

Run 107 completed `image_resolution` and failed at `publication_branch_creation`.
The shared `temp/target` checkout then contained a modified tracked hero image.
`ArticleImageHandler` writes downloaded and brief-uploaded assets under the
target checkout, while `TargetRepoPublicationWorkflow` creates the Git branch
later. `GitHubPublisher.create_branch()` expects checkout/rebase to start from a
clean tree, and its cleanup message hid the first Git error. The failed attempt
also left the article's publishing marker active.

## Scope

- Stage the resolved local image outside the target checkout during image
  resolution.
- After branch creation, atomically write the staged image through
  `TargetRepoWriter`, then write and validate the post as before.
- On branch-setup exceptions, release only the publishing marker owned by that
  attempt, using the existing branch and attempt-token guard.
- Include the original Git failure when cleanup verification also fails.
- Add regression coverage for clean checkout during branch setup, image write
  ordering, traversal-safe atomic asset writes, and release after branch setup
  failure.

Out of scope: changing image eligibility, editorial content, source rights,
branch naming, automatic push/PR policy, real GitHub publication, deployment,
the user's existing `temp/target`, and unrelated dirty files in the source
checkout.

## Design decisions

- Use a per-resolution temporary directory outside `target_dir`; the existing
  `ArticleImageHandler` can keep its download/materialization policy while
  writing into that isolated directory.
- Carry only the resolved asset filename and bytes as a typed pending asset on
  the per-article publication run and request.
- Write the asset after branch creation and before Markdown/frontmatter write,
  so the branch commit contains both files and the article continues to refer
  to the same `~/assets/images/<filename>` path.
- Do not clear or stash arbitrary dirty target files. The bug is fixed at the
  write ordering boundary, with test repositories isolated under `tmp_path`.

## Acceptance criteria

1. A resolved uploaded or downloaded image leaves the target Git tree clean
   until `create_branch()` has completed.
2. The selected branch contains the exact staged image bytes before the post
   write and validation stages run.
3. Image resolution keeps the same local URL, alt text, and origin metadata.
4. A branch setup failure releases the publishing marker for that exact
   attempt and preserves the original exception in diagnostics.
5. Existing image-wait/checkpoint behavior and non-image publication behavior
   remain unchanged.
6. Targeted regression tests and applicable repository gates pass. A local
   bare-Git workflow proves branch creation and asset/post writes without
   contacting GitHub. No live publish, push, PR, or deployment is performed.

## Verification

- Focused tests:
  `uv run pytest tests/unit/logic/workflows/test_refinery_engine.py tests/decompose_refinery/test_target_repo_publication.py tests/decompose_refinery/test_target_repo_writer.py`
- Broader workflow coverage:
  `make test-boundaries`, `make test-integration`, `make test-e2e`
- Baseline and output gates:
  `make lint`, `make type`, `make test`, `make quality-gate`
- Repository completeness:
  `make docs-check`, `make inventory-check`, and the plans-ledger validator
  (confirm exact target names in `make help`).
- Final diff, tracked-tree status, and preservation checks for the original
  dirty checkout and `temp/target` image.

Local gate success is not evidence of a live GitHub publication. The local
bare-Git test is the operational acceptance boundary for this code change.
