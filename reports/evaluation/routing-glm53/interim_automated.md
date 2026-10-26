# Interim automated metrics — LLM routing benchmark

## Arm A (nvidia/nemotron-3-super-120b-a12b)
- runs: 13 (ok 12, mixed 0, failed 1)
- schema_ok: 100%  |  critic: 0 approved / 0 judged / 12 ok (abstain = critic fail-open, tracked separately)
- wall p50/p95: 338.1s / 423.0s  |  llm calls: 54  |  failover-served: 0

## Arm C (z-ai/glm-5.3)
- runs: 17 (ok 11, mixed 0, failed 6)
- schema_ok: 100%  |  critic: 5 approved / 5 judged / 11 ok (abstain = critic fail-open, tracked separately)
- wall p50/p95: 360.6s / 585.8s  |  llm calls: 55  |  failover-served: 0

## Judge prod (23 judgments)
- arm A: 12/12 ok
- arm C: 11/11 ok

## Judge local (23 judgments)
- arm A: 12/12 ok
- arm C: 11/11 ok

## Cross-critic matrix (output-arm x critic-arm approval)
out\critic | A | C |
A | 10/11 | 9/11 |
C | 9/11 | 8/11 |

_Diagonal inflation (self-approval >> cross-approval) means the critic is lenient to its own model; read output-arm quality down the fixed-critic columns._
## Grounded fact-check (claims vs source content)
- arm A: 12/12 judged, 56 claims total
- arm C: 11/11 judged, 62 claims total

_Human blind ranks merged separately before thresholds apply._