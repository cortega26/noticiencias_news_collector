# Fixture maintenance

Status: Active. Tests and contracts own fixture behavior; this guide describes
how to change expectations without hiding a regression.

Locate the test that loads a fixture before modifying it. `tests/data/` includes
historical datasets as well as active cases. The retained
`tests/data/golden_articles.json` and `tests/data/collector_pipeline_chain.json`
were used by an older pipeline test that is no longer present; do not describe
them as a currently enforced end-to-end gate or run that removed test command.

For an intentional behavior or contract change:

1. Record the before/after behavior and affected boundary, then update only
   the fixture fields that should change. Preserve stable article identity.
2. Use fixed timestamps and provider responses for deterministic tests.
   Evaluate live providers separately from fixture assertions.
3. Review golden changes as expected behavior, not generated output to accept
   automatically. Retain counterexamples, error cases and quality thresholds
   unless evidence supports changing them.
4. Run the consuming tests plus the applicable contract/boundary gates.
   The current slow pipeline suite is `tests/e2e_pipeline/`, invoked through
   `make test-e2e` with ordering specified by the Makefile.
5. Commit fixture changes with the corresponding implementation and report
   which tests consumed them. An unreferenced fixture is not test coverage.

See `CONTRIBUTING.md` for scoring-golden maintenance and `docs/testing.md` for
system verification. No fixture or runtime prompt is changed by Plan 081.
