# Focused task template

Use this template to provide context without duplicating the repository's laws.

```markdown
**Task:**
[Concrete outcome, scope and relevant user constraints.]

**Evidence and source owners:**
[Relevant error, diff or reproduction; code paths and contracts to inspect.]
Read docs/SOURCE_OF_TRUTH.md and docs/AGENTS.md, then applicable module context.
Treat context notes as navigation aids and verify exact behavior in source.

**Consequential decisions and invariants:**
[Contracts to preserve, accepted compatibility changes, failure semantics.]
Use the actual LAW-B identifiers in docs/AGENTS.md; do not create new rules here.

**Acceptance and verification:**
[Observable outcomes and checks required for the change class.]
Record command results and meaningful limitations. Reuse the user's existing
authorization; resolve routine choices from source and established conventions.
Ask only when a consequential decision remains unresolved.

**Handoff:**
Summarize the result, changed files, verification and any unresolved issue.
Keep plans decision-complete; avoid restating mechanical implementation steps.
```
