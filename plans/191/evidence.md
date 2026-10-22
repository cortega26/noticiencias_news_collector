# Plan 191 execution evidence

This is local development evidence for the isolated branch `growth/editorial-pipeline-20261022` at base `1b948aed`. No PR, merge, deployment, public-runtime result or recorded human review is attested here.

## Source and evaluation controls

Already retrieved NASA material: https://science.nasa.gov/blogs/webb/2024/06/05/reconnaissance-of-potentially-habitable-worlds-with-nasas-webb/. The live input is an explicitly partial excerpt under `evidence/source-nasa-excerpts.txt`, with `summary_only` coverage. It is source material, not independently verified evidence. The eleven source-backed replay controls contain ten deliberately flawed candidates and one faithful control; literal assertions identify all ten controlled failures. These controls test the evaluator, not generated editorial quality. Human semantic labels remain pending in `tests/data/editorial_eval/evidence/review.json`.

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

## Final frozen-tree local gates

`evidence/final-local-gates.json` records `/tmp/noticiencias-pipeline-final-gates7.log`, exit 0. `make lint type test test-contracts test-boundaries quality-gate docs-check inventory-check` passed using the canonical installed environment read-only with its bootstrap stamp omitted. Type: mypy three files; unit coverage 4,462 passed/5 skipped/190 deselected in 155.45 seconds; 90.07% coverage versus 88.44% baseline and changed-file ratchet green. Separate `make test`: 4,462 passed/5 skipped/190 deselected in 97.42 seconds. Contracts: 310 passed; boundaries: three passed; quality: all three snapshots valid; documentation: fifteen docs valid; inventory drift: zero. Skips are explicit opt-in schema/environment/live-evaluation checks, not silently removed failures.

Preliminary runs are not presented as passes: formatting/complexity issues and a stale v4 cache-key assertion were corrected; gates6 was interrupted to include the final concrete feedback-selection fix. The final frozen source is covered by gates7. Exact file hashes are in `evidence/final-file-fingerprints.json`; historical capture runtime hashes remain distinct. No commit, push, PR, merge, deployment, public schema/status change or protected-setting mutation occurred in this worktree.

Final documentation-only checks also passed `docs-check inventory-check plans-ledger-check` in `/tmp/noticiencias-pipeline-final-docs2.log`. The pre-existing new plan row's invalid `IN PROGRESS` token/column shape was corrected to the supported `PARTIAL` status with the full ledger columns; semantic acceptance and parent integration remain pending.
