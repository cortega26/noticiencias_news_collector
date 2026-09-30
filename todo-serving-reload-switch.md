# TODO — SERVING_RELOAD switch

- [x] `__main__.py`: `_resolve_reload()` + wire into `uvicorn.run`
- [x] Tests: default, truthy/falsy matrix, garbage fail-closed, `main()` wiring
- [x] `admin_stack.sh` header + RUNBOOK note
- [x] `make lint` + focused tests (30 passed)
- [x] Live smoke: `SERVING_RELOAD=0` → no reloader child process, HTTP 200
- [ ] Inventory refresh after staging (new spec/todo pair)
- [ ] Commit + PR (pending user)
