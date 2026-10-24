# 191 — Evidence-first editorial pipeline

## Goals and contracts

Critical publication behavior change. Scientific Spanish must preserve source scope, uncertainty, figures and attribution throughout translation, adaptation, proofreading, headlines, enrichment, visuals and distribution. Source-support checking is not independent fact-checking. No public frontmatter/status changes and no fabricated human review.

## Implementation

- Revise the existing YAML prompts and code-owned technical/image/social prompts together.
- Build a bounded internal evidence brief from already retrieved source text before drafting: reader question, proposed contribution, URL, coverage, exact passages and source fingerprint. No new retrieval or fabricated primary evidence. Thread it into editor, repairs, headline and enrichment context, and the PR review packet with claim-support results and image provenance.
- Version every affected cache stage; bind enrichment to final candidate body and critic checkpoints to content. Bind critic checkpoints to candidate content and retain full source/prompt fingerprinting of durable drafts. Unverified critiques are explicit, non-checkpointable and cannot masquerade as approval. Material unsupported claims/close paraphrase block release; drafts remain available in stage artifacts.
- Known headline fidelity/sensationalism rejection also survives regeneration, empty output and failed re-review. Persist its concrete instruction and reviewed headline/body hashes within the article/source/prompt revision; only an explicit reviewed pass clears it.
- Known material findings survive no-op/changed repairs and infrastructure/malformed re-review until explicit successful material revalidation. Persist the concrete findings with the latest candidate hash in the source/prompt-bound critic artifact; never reuse a hold for another article, source or prompt revision.
- Generated article PRs start as drafts, bind the review checklist to final content/source/prompt fingerprints, and require final human review. Do not change protected GitHub settings or merge.
- Extend existing replay evaluation with source-backed negative controls and pending human labels; exercise configured stages in bounded isolated live runs. Transport/parser canaries are not semantic quality proof.

## Verification

Baseline and final `make lint`, `make type`, `make test`; targeted editorial/gate/cache/publication tests first; `make test-contracts`, `make test-boundaries`, `make quality-gate`, `make docs-check`, `make inventory-check`; `make llm-canary ARGS="--require-keys"`. Browser/public deployment and human semantic assessment belong to the parent rollout. Use existing canonical installed tools read-only with VENV override and bootstrap stamp omitted to avoid recreating canonical tooling. Report unavailable keys/providers or baseline failures honestly.

## CI dependency repair

The Code Quality gate found GHSA-83vg-56qc-22m7 in GitPython 3.1.61. Require the official patched release, GitPython >=3.2.1, and regenerate only that package through `scripts/sync_lockfiles.py --upgrade-package gitpython==3.2.1`; preserve unrelated pins and the existing audit policy. Update `docs/ci.md`, the dependency inventory and the final file fingerprint manifest. Existing publisher, orchestration, identity and lock-tool tests cover compatibility. Validate the actual new package in a task-isolated Python 3.13 environment, then run lint, type/unit coverage, units, contracts, boundaries, quality, quality-ci, lock parity, lock regeneration stability, docs and inventory checks. Preserve the canonical environment, editorial runtime, prompts, tests and immutable runtime captures. Dependency repair does not establish new live editorial evidence.

## Codacy repair boundaries

Separate evaluation CLI/input, budget, capture and report responsibilities, and group provider-seam/control tests cohesively, to meet method length/complexity limits without changing behavior or weakening assertions. Preserve immutable raw captures and pending human labels. Separate captured review-packet bytes into adjacent `.raw.txt` artifacts and render them literally in Markdown wrappers with their raw paths and SHA-256 hashes; preserve original capture lineage and terminal-LF recoverability. No editorial behavior, prompt, cache behavior or quality-policy changes are part of this repair; the sole editorial runtime refactor is the bounded digest cleanup specified below.

Verify targeted evaluation tests and the reported static-analysis findings, exact archived/raw byte equality and original-capture recoverability, Markdown structure and `git diff --check`. Parent integration and human semantic acceptance remain pending.

## Bounded editorial digest cleanup

Add `editorial_text_sha256(text: str) -> str` to the existing pure
`editorial/draft_identity.py` module and reuse it in the two production consumers:
`components/editorial/ai_editor.py` and `editorial/evidence_brief.py`. Hash the exact
UTF-8 text, with no normalization, media filtering or version prefix. Keep all
caller-owned JSON serialization options, 24-character revision slices, persisted
keys, cache semantics and editorial holds unchanged; `editorial_fingerprint`
retains its distinct serialization contract. Remove the unused AI editor
`hashlib` import. Do not refactor legacy classes, change analyzer thresholds or
claim the pre-existing AI editor file-length debt is resolved.

Verify the original and extracted hashes byte-for-byte for empty text, Unicode,
whitespace and caller-serialized JSON; add characterization coverage to the
existing editorial draft tests. Run real temporary-file cache, evidence brief,
headline and material-hold regression tests using fake transport seams only.
Run focused formatter/import/lint checks; the parent verification pass owns the
required final `make lint`, `make type` and `make test` gates. No live LLM calls,
fingerprint inventories, commits, pushes or deployment are part of this cleanup.

The final coordinator uses the isolated Python 3.13 / GitPython 3.2.1 environment,
not the canonical environment used by historical verification. It additionally
runs existing integration and pipeline E2E suites once. The task-only frontend
parity symlink selects the reviewed full frontend in the existing E2E harness;
record that optional real-frontend mode separately from synthetic fixture runs,
with its existing per-test timeouts and any failures preserved. Do not change
timeout policy or retry for a favorable result.

## Runtime evidence and review boundaries

Initial baseline checks passed 4,383 tests (40 skips before frontend parity mount). Earlier targeted editorial/publication suite passed 655 tests with one opt-in local-live skip. The final safety regression subset passes 166 tests, including material/close-paraphrase and headline holds across timeout/malformed re-review, changed repair, durable resume, explicit clearing and article/source/prompt isolation. Required configured scoring canary passed 5/5 real LLM items in 1.4 seconds; it is not semantic editorial evidence.

Sanitized immutable captures, source excerpts, held draft/issue packet and exact limitations are retained under `plans/191/evidence/` and explained in `plans/191/evidence.md`. Paired trial 3 completed the old-prompt baseline and held the candidate for an unsupported Mars claim. The single post-fix candidate attempt was held for close paraphrase and then failed technical repair validation after provider 404/429. No successful live candidate draft or human semantic acceptance was obtained. Final additional safety edits have deterministic tests and independent review; their exact final runtime has not been run live. No more live retries are authorized for this task.

Temporary task-owned frontend parity symlink: /home/carlos/VS_Code_Projects/_worktrees/noticiencias -> /home/carlos/VS_Code_Projects/_worktrees/noticiencias-growth-experience-20261022, created only after root authorization and absence check. Target is read-only to this task; remove only this symlink after verification if no other task depends on it.
