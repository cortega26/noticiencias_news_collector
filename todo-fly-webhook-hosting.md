# Todo: Fly.io webhook hosting (see spec-fly-webhook-hosting.md)

## Infra artifacts

- [x] `Dockerfile.serving` — python:3.13-slim, installs `news_collector` + `noticiencias`, uvicorn on 0.0.0.0:8000.
- [x] `docker-compose.serving.yml` — serving + cloudflared local parity stack (quoted `${VAR:?msg}` values).
- [x] `fly-serving.toml` — app `noticiencias-serve`, region `cdg`, port 8000, 256mb.
- [x] `fly-tunnel.toml` — app `noticiencias-tunnel`, process `tunnel run` (no `cloudflared` prefix), 256mb.

## Deployment

- [x] App `noticiencias-serve` created + deployed (2 machines, cdg) — serves 405 on the endpoint.
- [x] App `noticiencias-tunnel` created + deployed with `--image cloudflare/cloudflared:latest`
      (first attempt without `--image` built the full collector image → machine crashed → destroyed).
- [x] Tunnel route configured via Zero Trust API: `api.noticiencias.com` →
      `https://noticiencias-serve.fly.dev` (`.internal` rejected: separate per-app networks).
- [x] Redundant stopped machine `784991eb065908` destroyed.

## Cutover

- [x] Local systemd `cloudflared` stopped + disabled (operator action).
- [x] Local uvicorn (`:8000`) killed; `~/.cloudflared/config.yml` removed (remotely-managed tunnel).
- [x] Regression: fly-only POST → 202; `backend-notify.js` real envelope → 202.

## Docs

- [x] `docs/RUNBOOK_LOCAL_DEV.md` — new "Webhook hosting (production)" section (deploy commands,
      `--image` requirement, public-URL route rationale, local connector retirement date).
