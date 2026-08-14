# Spec: Refinery GUI — Phase 4 addendum (source editor)

## Goals

Close the last parity gap with the old Streamlit GUI: **source creation and
editing**. The old GUI's "Editar / Agregar Fuente" form lets the operator add
a new source or edit an existing one (name, URL, credibility, category,
update frequency, group), preserving unedited keys (e.g. `blacklisted`,
`etag`). Delete already exists (Phase 4).

Same governance: the endpoint dispatches to the existing
`save_sources` (config/sources.py) + `SourceRepository` init/update path;
no new write logic authored in serving.

## Endpoint

| Endpoint | Method | Purpose | Backend source |
|---|---|---|---|
| `/v1/admin/sources` | POST | Add or update a source | `ALL_SOURCES` update (preserve existing keys) + `save_sources` + `initialize_sources` (DB row) |

Body: `AdminSourceUpsert` — the exact editable fields of the old form:

- `source_id` (str, snake_case, required — the key; immutable on update)
- `name`, `url` (required)
- `credibility_score` (float 0..1, default 0.8)
- `category` (one of the old GUI's list)
- `update_frequency` (daily/weekly/hourly/multiple_daily)
- `_group` (ELITE_JOURNALS/SCIENCE_MEDIA/INSTITUTIONAL_SOURCES/AI_LABS/CUSTOM)

Merge semantics (mirror the old GUI): on update, start from the existing
entry dict and overlay only the provided fields — `blacklisted`, `etag`,
`last_modified`, `content_mode` etc. are preserved. On create, seed the
old GUI's defaults (`language=en`, `description=Added via UI`,
`typical_delay=0`).

After the yaml write, call `initialize_sources` (or a new narrow
`SourceRepository.upsert_source`) so the DB row exists for circuit state
— same behavior the collector gets from config.

## GUI

- **Sources page**: header gains "Add source" button → inline editor card
  (or modal) with the same fields; each row gains "Edit" that loads the
  form prefilled. Save → POST; toast on success/validation error.
- Client: `upsertSource(payload)` in api.ts + types + vitest.

## Out of scope (unchanged)

- Secrets management (never via the API).
- Group/category option lists are hardcoded to the old GUI's values in the
  contract (adding new groups later is a contract change).

## Verification

1. API tests:
   - create: new source appears in ALL_SOURCES + yaml file + DB row;
     defaults seeded.
   - update: existing keys (blacklisted, etag) preserved, edited fields
     applied.
   - validation: missing name/url → 422; bad category → 422; bad
     credibility range → 422.
2. GUI vitest for `upsertSource` (mocked fetch).
3. Live browser e2e: add a throwaway source, verify it appears; edit it;
   delete it (Phase 4 endpoint) to leave no residue.
4. All existing gates: lint, type, test, test-contracts, test-boundaries,
   admin-test, admin-build, docs-check.
