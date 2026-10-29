# Plan 208 todo

- [x] Confirm failure evidence and current checkout state; create isolated worktree.
- [x] Add a regression test proving image resolution does not dirty the target checkout before branch creation.
- [x] Move resolved image writes to the branch-selected publication stage.
- [x] Release attempt-owned publishing state on branch-setup failure and preserve the original exception as the cause.
- [x] Run focused tests, local bare-Git publication simulation, and required repository gates.
- [x] Review the diff and confirm original worktree WIP and failed-run image remain untouched.
- [x] Record exact commands/results in `tests/README.md` and close plan status accurately.
