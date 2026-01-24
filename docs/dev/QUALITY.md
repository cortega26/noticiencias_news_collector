# Code Quality & Security

This project employs a suite of static analysis tools to ensure code quality, type safety, and security.

## Quick Start

### Run All Checks

```bash
make quality
```

### Auto-Fix Issues

```bash
make quality-fix
```

- Runs `ruff --fix` (imports, formatting, simple refactors).
- Then runs the full quality suite.

### CI Strict Mode

```bash
make quality-ci
```

- Used by GitHub Actions.
- No auto-fixing.
- Fail-fast on first error (mostly).

## Tools Configured

| Tool          | Purpose                                  | Config File                    |
| :------------ | :--------------------------------------- | :----------------------------- |
| **Ruff**      | Linting, Formatting, Imports, Complexity | `pyproject.toml`               |
| **Mypy**      | Static Type Checking                     | `pyproject.toml`               |
| **Bandit**    | Python Security Linter                   | `pyproject.toml`               |
| **Semgrep**   | SAST (Advanced Security Patterns)        | `.semgrep.yml`                 |
| **pip-audit** | Dependency Vulnerability Scanning        | `pyproject.toml` (via CI/Make) |

## Interpreting Failures

### Ruff

- **Format**: `file.py:line:col: RULE_ID Message`
- **Fix**:
  - Most are auto-fixable with `make quality-fix`.
  - For complexity (`C901`), refactor the function.
  - For others, check the rule code (e.g., `S101` = existing usages of `assert`).

### Mypy

- **Error**: `Incompatible types` or `Item "None" of "Optional[...]" has no attribute ...`
- **Fix**: Add type assertions, handle `None` checks, or update type hints.

### Security (Bandit/Semgrep)

- **Bandit**: Reports `High`/`Medium` severity issues.
- **Semgrep**: Reports pattern matches keying on security risks.
- **Fix**:
  - If false positive: Add `# nosec` (Bandit) or `# nosemgrep` (Semgrep) with a comment explaining why.
  - If true positive: Fix the vulnerability (e.g., use `subprocess.run` with `check=True` and no `shell=True`).

## Adding Ignores

Ignores should be used sparingly and always with justification.

### Ruff

Global ignores in `pyproject.toml`:

```toml
[tool.ruff.lint]
ignore = ["E501"] # Line length handled by black
```

Per-file ignores:

```toml
[tool.ruff.lint.per-file-ignores]
"tests/*" = ["S101"] # Allow assert in tests
```

### Mypy

Per-line ignore:

```python
x = check()  # type: ignore[attr-defined]
```
