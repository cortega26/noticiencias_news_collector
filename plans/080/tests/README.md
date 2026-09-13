# Acceptance evidence and intended tests

This planning task changes documentation only. There are no new executable tests
here yet, and no claim that the planned implementation passes. Implementers add
behavioral tests to the existing suite at the paths below, then put their command
results and review evidence in this directory.

| Acceptance | Intended executable evidence | Evidence document to create |
| --- | --- | --- |
| W1–W5 | **New** `tests/property/test_workflow_lifecycle_stateful.py`; existing workflow unit suites and `tests/test_serving_admin_api.py` | `phase-1-results.md` |
| A1–A5 | **New** `tests/contracts/test_admin_openapi.py`; existing admin API/client tests; actual exporter and generator stale-artifact probes | `phase-2-results.md` |
| E1–E5 | **New** `tests/unit/test_editorial_eval.py`; existing generated-Markdown guardrail tests; actual installed Promptfoo passing/failing offline runs | `phase-3-results.md` |
| V1 | Diff review and the union of relevant successful phase gates | `final-results.md` |

Paths in the table are relative to the repository root. Evidence filenames are
relative to this directory. Each results document should contain the checkout
revision, relevant dirty-state note, command, exit code, acceptance IDs, actual
observations, failures, and reviewer disposition. Do not copy full secrets,
environment dumps or large runtime reports into evidence.

The first implementation session also creates `baseline.md` here. References to
future test/results files in this plan are intentional, not missing artifacts
that the planning task should fabricate.
