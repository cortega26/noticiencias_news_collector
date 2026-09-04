# Plan 070 — Counterweight hooks: stakes (+question stays out)

## Decision

Voice §2.4.3 names the curiosity gap; stakes hooks ("lo que X cambia
para ti") over preliminary findings carry the same promise-to-reader
dynamics, so they join the forcing set. `question` stays OUT: interrogative
hooks are normally answered in-body and the fidelity critic already judges
hook-body match — forcing caveats there would spray amber boxes and dilute
the signal. Counterintuitive/human_emotion likewise stay out (data-anchored
by construction). Precision is guarded twice: hook must match AND
confidence must read preliminary.

## Design

- `uncertainty.py`: `_CURIOSITY_HOOK` → `_COUNTERWEIGHT_HOOKS =
  frozenset({"curiosity_gap", "stakes"})`; same normalization; docstrings
  updated (module + function + plan reference).
- Tests: stakes+Moderada ⇒ forced; question+Moderada ⇒ untouched;
  existing matrix intact.

## Verification

- `make lint` + targeted editorial suites (rule change → full `make test`
  for the shared file per matrix; no orchestration touch).
