# Acceptance scenarios

Executable regressions live in existing unit/serving/integration suites and
`tests/unit/logic/workflows/test_image_independent_processing.py`. Each scenario
must exercise repository code with temporary SQLite/files and explicit outcomes.
See ../spec.md Verification for the full acceptance matrix.

See [validation results](results.md) for gate counts, database-copy acceptance,
publication PR evidence, browser limitations and the pending release boundary.
Generation provenance is in [3822-image-generation.json](3822-image-generation.json).
