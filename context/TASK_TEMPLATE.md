# Token-Efficient Task Prompt Template

```markdown
**TASK**:
[1-2 sentences explaining what needs to be accomplished]

**REQUIRED CONTEXT REFS**:

- `context/INVARIANTS.md`
- `context/MODULE_INDEX.md`
- [List specific `context/modules/<slug>.md` files needed]

**MINIMAL EVIDENCE**:
[Provide a minimal diff, target function snippet, or specific error logs]

- If no diff: provide (a) exact function/class name, (b) file path, (c) error log lines.
  \`\`\`diff
  --- a/path/to/file.py
  +++ b/path/to/file.py
  @@ -10,3 +10,3 @@
- old_function(param1):

* new_function(param1, param2):
  \`\`\`

**CONSTRAINTS & INVARIANTS**:

- Adhere strictly to `docs/AGENTS.md` core laws (e.g., LAW-1 Data Contracts, LAW-2 Adapters).
- Obey invariants defined in the module's context file.
- Do NOT rewrite or modify functionality outside the exact scope.

**CHECKS**:
[List validation commands, e.g.:]

- `make test-contracts`
- `make test-boundaries`
- `pytest path/to/specific_test.py`

**STOP CONDITIONS**:
Ask for clarification BEFORE making changes if:

- Context files are missing or invariants contradict the request.
- Changes require altering sealed contracts or boundary adapters without explicit permission.

**OUTPUT FORMAT**:

- Output unified diffs ONLY for the modified files.
- Provide a 1-2 sentence summary of changes.
- Do NOT output full file contents.
```
