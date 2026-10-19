# Spec: Deploy webhook hosting to Fly.io (production cutover)

## Goals

- Serve `POST https://api.noticiencias.com/api/v1/webhook/frontend` (the frontend CI
  callback) from the cloud so it does not depend on a local PC.
- Provide reproducible deploy artifacts for the Fly.io apps `noticiencias-serve`
  (FastAPI) and `noticiencias-tunnel` (Cloudflare Tunnel connector).
- Document the hosting topology and its gotchas in `docs/RUNBOOK_LOCAL_DEV.md`.
- Cut over cleanly: retire the local tunnel connector and local uvicorn.

## Implementation details

New files (repo root):

- `Dockerfile.serving` — `python:3.13-slim`, installs the project (including the
  `noticiencias` package; without it the app crashes with `ModuleNotFoundError`),
  runs uvicorn on `0.0.0.0:8000`.
- `docker-compose.serving.yml` — local parity stack: `serving` (env
  `WEBHOOK_API_KEY`) + `tunnel` (cloudflared image, `TUNNEL_TOKEN`). YAML values
  quoted to survive `${VAR:?msg}` parsing.
- `fly-serving.toml` — app `noticiencias-serve`, region `cdg`, HTTP service port
  8000, `shared-cpu-1x:256mb`.
- `fly-tunnel.toml` — app `noticiencias-tunnel`, region `cdg`, process `tunnel run`
  (entrypoint of the cloudflared image is already `cloudflared`; do not prefix it),
  `shared-cpu-1x:256mb`.

Topology decisions (documented in the runbook):

- Tunnel `noticiencias-webhook` is remotely managed (dashboard). Deploy its
  connector with `fly deploy --config fly-tunnel.toml --image cloudflare/cloudflared:latest`
  — `[image]` in the toml is ignored by Fly.
- Route: hostname `api.noticiencias.com` → `https://noticiencias-serve.fly.dev`.
  NOT `noticiencias-serve.internal`: each Fly app gets its own private network, so
  internal DNS does not resolve across apps (verified live: `socket.gethostbyname`
  fails for both app names from inside the serving app).

## Verification

All executed 2026-08-04 (UTC-4):

- [x] `docker build -f Dockerfile.serving .` succeeds; container responds HTTP 422
      (schema validation → pipeline alive) on a malformed payload.
- [x] `https://noticiencias-serve.fly.dev/api/v1/webhook/frontend` → HTTP 405 (FastAPI up).
- [x] POST valid envelope to `api.noticiencias.com` → HTTP 202
      `{"accepted":true,"event":"validation_result"}` (served by Fly connector).
- [x] POST without token → HTTP 401 (fail-closed auth intact).
- [x] `node scripts/backend-notify.js --status=pass --payload-file=...` (real CI
      envelope, same env vars) → `Notification sent (202)`.
- [x] Post-cleanup regression: local tunnel stopped + local uvicorn killed → still 202.
- [x] `fly machine list -a noticiencias-tunnel` → exactly one started machine.

No Python code touched → no `make lint/type/test` beyond a sanity check required
(change matrix: docs + infra only).
