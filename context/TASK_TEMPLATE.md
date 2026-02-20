# Token-Efficient Task Prompt Template

Use this template to significantly reduce token consumption (60–90% reduction) when requesting engineering tasks. Instead of sending full source code files, rely on the pre-generated module index and context files to provide the AI with only what it needs.

---

## 📋 Task Request Template

```markdown
**Task Goal:**
[1-2 sentences explaining what needs to be accomplished]

**Target Modules:**
[List the specific module names or paths that need to be modified. Only list modules that require actual code changes.]

- `news_collector/example/module.py`

**Reference Context:**
[Instead of pasting code, tell the AI which context files to read for dependencies and invariants.]

- Read the module index: `context/MODULE_INDEX.md`
- Read the context files: `context/modules/example_module.md`

**Current State (Minimal Diff):**
[If modifying a specific function or class, provide ONLY the relevant snippet or a minimal diff, not the entire file.]
\`\`\`diff

- old_function(param1):

* new_function(param1, param2):
  \`\`\`

**Modification Instructions:**
[List clear, step-by-step instructions for the changes required.]

1. [Step 1]
2. [Step 2]

**Safety & Invariants Check:**

- Ensure the changes adhere to the invariants listed in the module's context file.
- Do these changes violate any architectural rules defined in `docs/AGENTS.md`? [Yes/No]
- Run tests: [Specify tests to run, e.g., `make test-contracts` or `pytest path/to/test.py`]
```

---

## 💡 Best Practices for Token Efficiency

### 1. Specifying Module Context Without Full Code

Never paste entire `.py` files into the prompt. The AI agents are instructed to independently fetch and read the `context/MODULE_INDEX.md` and the individual `context/modules/*.md` files. This gives them the dependencies, roles, outputs, and invariants of a module at a fraction of the cost.

### 2. Including Minimal Diffs

When asking for a change to an existing file, only provide the lines that need to change and a few lines of surrounding context. Use standard diff format (`+` for additions, `-` for removals). If you don't have a diff, just provide the exact name of the function or class to target.

### 3. Referencing Module Context Files

Direct the AI to the pre-generated context files. For example:

> "Before modifying `router.py`, read `context/modules/enrichment_router.md` to understand its role and failure modes."

### 4. Requesting Changes Safely

Always tie task requests back to the project's architectural laws.

- Explicitly ask the AI to verify that `AGENTS.md` invariants (like `LAW-1` or `LAW-4`) are not broken.
- Specify exact validation commands (e.g., `make test-boundaries`) to be run after the code modifications are made.
