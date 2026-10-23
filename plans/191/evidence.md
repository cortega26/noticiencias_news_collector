# Plan 191 execution evidence

This is local development evidence for the isolated branch `growth/editorial-pipeline-20261022` at base `1b948aed`. No PR, merge, deployment, public-runtime result or recorded human review is attested here.

## Source and evaluation controls

Already retrieved NASA material: [Reconnaissance of Potentially Habitable Worlds with NASA’s Webb](https://science.nasa.gov/blogs/webb/2024/06/05/reconnaissance-of-potentially-habitable-worlds-with-nasas-webb/). The live input is an explicitly partial excerpt under `evidence/source-nasa-excerpts.txt`, with `summary_only` coverage. It is source material, not independently verified evidence. The eleven source-backed replay controls contain ten deliberately flawed candidates and one faithful control; literal assertions identify all ten controlled failures. These controls test the evaluator, not generated editorial quality. Human semantic labels remain pending in `tests/data/editorial_eval/evidence/review.json`.

## Actual editorial chain

The tool invokes `EditorAgent.prepare_article`, with the configured provider order and models. Evaluation-only limits cap provider time/retries/tokens and source-support calls (30 seconds, zero retries); production configuration and credentials are unchanged. The configured NVIDIA endpoint returned HTTP 404 and fallback to Gemini was exercised. The local source-support model can time out; a transport/parser canary cannot establish claim entailment.

- Trial 1 retained under `evidence/trial1-*`: shared call-budget bias prevented a fair paired comparison. Failed execution, not a quality pass.
- Trial 2 retained under `evidence/trial2-*`: stages ran but the harness omitted an explicit publication date, so assembly failed. This harness defect was fixed and regression-tested. Failed execution, not a quality pass.
- Paired trial 3 retained under `evidence/paired-trial3-*`: both labels use the same runtime, with independent maximums of 16 calls and 600 seconds. **This compares old/new prompts on the current runtime, not old/new runtime chains.** Baseline completed 9,157 characters in 16 calls/314.49 seconds; its material review is explicitly unverified because the old prompt omitted the support field. Candidate used seven calls/106.96 seconds and was held with `E_EDITORIAL_EVIDENCE`: an invented claim that Mars is in the Sun's habitable zone survived repair. The concrete support issue is preserved in the report. This demonstrates a material safety hold, not a semantic quality pass or candidate-draft completion.

## Independent review P1 regression

Review reproduced a known-material-finding bypass: rejection, no-op repair, then timeout/malformed re-review could clear the finding and return a non-checkpointable pass. The repair retains the concrete finding through unverified re-review and binds the pending hold to the latest draft plus article/source/prompt revision. Changed repair requires successful explicit material/value-add revalidation. Valid revalidation replaces the finding and creates a reviewed checkpoint. The critic artifact records both the original reviewed content hash and the latest candidate hash; it is only an approval when `approved=true`. Other articles/source/prompt revisions are isolated.

`/tmp/noticiencias-pipeline-p1-regression.log`: 37 targeted tests passed, covering real preparation/gating/repair with only provider I/O replaced. These tests include twelve timeout/malformed/incomplete re-review × no-op/changed-repair × unsupported/close-paraphrase combinations, plus successful verified repair and three article/source/prompt-isolation cases. Resume retries preserve a concrete issue and cannot publish. A provider-faked success is not live semantic proof.

Final mandatory gates and the single post-fix candidate attempt are recorded below after completion. Human editorial acceptance, production runtime and deployment remain unverified.

## Single post-fix candidate attempt

`evidence/candidate-trial4-*` retains the actual bounded capture, held stage-2 draft and reconstructed issue packet. Six calls/148.57 seconds; no completed candidate draft. The critic found `close_paraphrase` and recorded that the body reproduced the source structure/content without analysis. Repair then failed technical revalidation (`E_EDITORIAL_REPAIR_TECHNICAL`: canonical James Webb Space Telescope naming), and publication remained held. The provider cascade encountered NVIDIA HTTP 404 and Gemini/Groq HTTP 429. Provider/model selection and credentials were unchanged. This is observed safety behavior plus a provider/technical limitation; it does not establish quality improvement.

The capture records runtime SHA-256 `765a25b0cfa232d6b71da03660bc14b72928de88ddaacd4f5ec8c281d1d9e48d`, an intermediate P1 patch. Subsequent independent review additionally closed resume-technical-repair and headline-rejection loopholes. Those final edits have deterministic regression/reviewer evidence, not a fresh live chain run. The authorized single post-fix attempt was consumed; no repeated live attempts were made to obtain a favorable draft. Configured scoring canary previously passed 5/5 LLM items in 1.4 seconds, but does not measure the editorial chain's semantic performance.

Headline review now also retains concrete fidelity/sensationalism failures across timeout/malformed re-review, empty regeneration and resume; only explicit reviewed approval clears them. Its artifact records the body and reviewed-headline hashes within the article/source/prompt revision. The empty-generation regression exposed and fixed a pre-existing uninitialized parser variable, preserving the intended bounded retry behavior.

## Final independent safety review

`evidence/independent-safety-review.json` records fourteen independent adversarial cases: the original editorial technical-repair resume exploit, twelve headline fidelity/sensationalism × timeout/malformed/empty × same/changed-title cases with new-agent durable resume, and rejection of a positive editorial checkpoint after body changes. All fourteen passed; the reviewer also ran 134 focused tests. These are code-agent/deterministic checks, not human editorial labels. The final small feedback-selection change additionally ensures that a concrete support issue reaches the actual repair prompt when the critic supplies blank feedback, rather than misdirecting repair toward a high style score. All 35 evidence regressions pass.

## Historical pre-digest frozen-tree local gates

`evidence/final-local-gates.json` records `/tmp/noticiencias-pipeline-final-gates7.log`, exit 0. `make lint type test test-contracts test-boundaries quality-gate docs-check inventory-check` passed using the canonical installed environment read-only with its bootstrap stamp omitted. Type: mypy three files; unit coverage 4,462 passed/5 skipped/190 deselected in 155.45 seconds; 90.07% coverage versus 88.44% baseline and changed-file ratchet green. Separate `make test`: 4,462 passed/5 skipped/190 deselected in 97.42 seconds. Contracts: 310 passed; boundaries: three passed; quality: all three snapshots valid; documentation: fifteen docs valid; inventory drift: zero. Skips are explicit opt-in schema/environment/live-evaluation checks, not silently removed failures.

Preliminary runs are not presented as passes: formatting/complexity issues and a stale v4 cache-key assertion were corrected; gates6 was interrupted to include the final concrete feedback-selection fix. That historical pre-digest frozen source was covered by gates7. Its AI editor fingerprint was `f6d593351afe664e6350a298694f59e150c26b675f1f67bccf08edc7ede9a380`; the current digest extraction and local verification are recorded separately below. Historical capture runtime hashes remain distinct. No commit, push, PR, merge, deployment, public schema/status change or protected-setting mutation occurred at that historical verification checkpoint.

Final documentation-only checks also passed `docs-check inventory-check plans-ledger-check` in `/tmp/noticiencias-pipeline-final-docs2.log`. The pre-existing new plan row's invalid `IN PROGRESS` token/column shape was corrected to the supported `PARTIAL` status with the full ledger columns; semantic acceptance and parent integration remain pending.

## Archived packet representation

The [candidate trial 4 packet](evidence/candidate-trial4-review-packet.md) and [paired trial 3 baseline packet](evidence/paired-trial3-baseline-review-packet.md) are literal display wrappers. Their adjacent [candidate raw archive](evidence/candidate-trial4-review-packet.raw.txt) and [baseline raw archive](evidence/paired-trial3-baseline-review-packet.raw.txt) preserve every byte of the previously archived `.md` packets; each wrapper identifies its raw SHA-256 and capture lineage. The baseline raw archive retains the previously documented one-terminal-LF normalization: removing exactly its final LF recovers the original captured packet. The held draft, source excerpts, capture JSON/JSONL and historical runtime fingerprints remain unchanged. This representation change adds no runtime or human semantic acceptance evidence.

## Codacy repair and exact digest preservation

Evaluation capture now separates CLI/input, budgets, execution and report writing.
Provider-seam tests live together in `tests/unit/editorial/evidence_pipeline.py`.
The previous helper accepted `technical_scores` but always returned 95, so the
former technical-repair regression did not exercise its requested zero score.
The repaired seam consumes the sequence; the regression now observes
`[95, 95, 0, 95]`, the actual changed technical-repair candidate, the concrete
repair prompt and the material hold after durable resume. This strengthens the
regression evidence; it does not retroactively validate that former branch.

The existing identity module now provides exact UTF-8 text SHA-256 to two real
production consumers. The 11 original consumer expressions and their extracted
replacements produced identical outputs in all 22 empty/Unicode cases. Caller
JSON options, revision slices, cache keys and material/headline holds retain
their contracts. The focused digest suite passed 72 tests. The earlier capture
refactor proof's runtime-equality field describes its pre-digest checkpoint,
not the final runtime after this extraction.

The current AI editor SHA-256 is
`28d0deba62710a2b8ee91562afdaf4913be1a4f49c29bfdb81a4fca5e4a38dfa`.
Prompts remain
`9d6a24d171e94bc86c5477891a93146fa4c7249af0ae94702338a286174c7d7f`.
The final file manifest fingerprints the current files; captured intermediate
runtime hashes and captured JSON/JSONL remain unchanged. The two raw packets
match their former archived Markdown bytes exactly, and the baseline original
capture remains recoverable by removing exactly one terminal LF.

Codacy's same-file length warning existed on the base at 2,043 non-comment
lines, and the reviewed head reported 2,361 against the configured threshold of
500. Lizard 1.24.0 reproduces that head count and measures 2,348 after the bounded
digest extraction. This is pre-existing debt plus remaining branch growth.
No analyzer threshold, suppression, protected setting or policy was changed;
no hosted Codacy reanalysis or clearance is inferred from local checks.

No new provider calls or live editorial attempts were made. These repairs add
local deterministic evidence, not a successful live candidate, new canary,
human semantic acceptance or deployed-runtime proof. Plan 191 remains `PARTIAL`.

## Current final local verification

The isolated Python 3.13.12 / GitPython 3.2.1 environment ran the existing gates
with its bootstrap stamp omitted. `make lint` passed; `make type` checked three
mypy files and passed 4,474 unit tests, with five explicit skips and 190
deselections, in 129.37 seconds. Coverage was 90.08% against the 88.44% baseline;
the changed-file ratchet passed. Separate `make test` passed the same 4,474 tests
in 98.76 seconds. Contracts passed 310, boundaries passed three, and all three
quality snapshots were valid. Integration passed 116 with one real-network
opt-in skip; the separate root E2E-marked group passed 189.

The optional full-frontend pipeline run selected the reviewed frontend through
the task-only parity sibling. The `stuck_publishing_recovery` scenario hit its
existing 300-second test timeout while Astro actively built the copied site
(output grew from 84 to 104 MB). After that actual failure, only the task-owned
process group was terminated; no owned children remained. The full command
therefore ended with 143 and is not an all-target pass or a 14-case site result.
The log is `/tmp/noticiencias-delivery-20261022/backend-final-codacy-gates.log`.
No timeout or production policy was changed. This observed full-site budget
limit is distinct from evidence of a digest regression; its exact cause was
not established by rerunning the old runtime.

A separate `make test-e2e` used the existing synthetic CI-style default, with
only the owned parity link temporarily absent, and passed all 14 cases in
28.61 seconds. The exact same symlink inode was restored afterward. This is
fixture evidence, not a passed full-site pipeline run. That command also
passed documentation (15 files), inventory (zero drift), the plans ledger and
the weak-test ratchet (36 assertion-free tests against baseline 36). Its log is
`/tmp/noticiencias-delivery-20261022/backend-final-synthetic-and-docs.log`.

`evidence/final-local-gates.json` preserves the historical results and adds these
current results, including the optional timeout. Inventory refresh changed only
its generation timestamp. Final fingerprints include 63 files and exclude the
manifest itself; the branch changes 64 files relative to its recorded base.
The reported Markdown spacing/list/bare-link rules are clean without rule
suppression; default lint still reports pre-existing long lines and preserved
literal packet content. Hosted Codacy reanalysis, parent integration and human
semantic acceptance remain pending.
