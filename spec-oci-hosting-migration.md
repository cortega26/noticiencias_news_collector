# Spec: migrate the serving layer from Fly.io to the always-free OCI VM

Status: done · 2026-09-26 (cutover verified; both Fly apps destroyed)

## Goal

Run `noticiencias-serve` (FastAPI/uvicorn) and its Cloudflare Tunnel connector on
the existing **always-free OCI Ampere A1 VM** (`159.112.147.154`,
`sa-santiago-1`, Ubuntu 22.04 ARM64, 2 OCPU / 12 GB, 97 GB disk) that already
runs Pogo-lab production, then retire the two paid Fly.io apps
(`noticiencias-serve`, `noticiencias-tunnel`).

Keeps public contracts unchanged: `https://api.noticiencias.com`
(webhook + admin, same paths, same keys) and the frontend's
`BACKEND_WEBHOOK_URL`/`BACKEND_ADMIN_URL`.

## Result (2026-09-26)

Done. The service and its connector run on the OCI VM; the Cloudflare tunnel
ingress points at `http://localhost:8010` (account
`7e153214690ac7430fde021f1f2b2916`, tunnel
`5a22de3a-2e80-4c90-9817-ce2ca830c889`); a unique marker request was observed
in the VM service journal and Fly received no further traffic; both Fly apps
were destroyed and the public endpoint stayed at 200. Cost: $0 on OCI within
the Always Free allocation. See `todo-oci-hosting-migration.md` for the
verification record and follow-ups.

## Current topology (Fly)

- `noticiencias-serve` (Fly, cdg): Docker image `Dockerfile.serving`, uvicorn
  :8000, env `NOTICIENCIAS__APP__ENVIRONMENT=production`, `WEBHOOK_API_KEY`,
  `ADMIN_API_KEY`; SQLite `data/news_v3.db` on the ephemeral rootfs (resets on
  deploy — no volume).
- `noticiencias-tunnel` (Fly, cdg): cloudflared connector for the remotely
  managed tunnel `noticiencias-webhook`; ingress
  `api.noticiencias.com -> https://noticiencias-serve.fly.dev`.
- Cost: ~$4.40/month for the two always-on 256MB machines (legacy free
  allowance may cover it; not guaranteed).

## Target topology (OCI VM, co-hosted with Pogo-lab)

- Source at `/opt/noticiencias-serving` (rsync of the backend repo: minimal
  copy — `config.toml`, `news_collector/`, `noticiencias/`, `pyproject.toml`,
  `README.md`, `LICENSE`), Python 3.13 via `uv`, venv `.venv`.
- systemd unit `noticiencias-serving.service` → uvicorn on `127.0.0.1:8010`
  (Pogo-lab already owns :8000).
- Env file `/etc/noticiencias-serving.env` (root, 0600):
  `NOTICIENCIAS__APP__ENVIRONMENT=production`, `WEBHOOK_API_KEY`,
  `ADMIN_API_KEY` — values reused from Fly so the frontend secrets stay valid.
- SQLite persists at `/opt/noticiencias-serving/data/news_v3.db` (durable,
  unlike Fly).
- cloudflared: second connector for the same `noticiencias-webhook` tunnel
  (systemd `cloudflared-noticiencias.service`, `--token`), or reuse the
  existing local tunnel via ingress; the remotely managed tunnel keeps its
  DNS CNAME, only its public-hostname service changes to
  `http://localhost:8010`.

## Migration sequence (no-outage order)

1. Deploy the service on the VM; verify `curl 127.0.0.1:8010/healthz`.
2. Start a VM cloudflared connector for `noticiencias-webhook` while the Fly
   connector still runs (both forward to the Fly origin; harmless).
3. Stop the Fly tunnel connector app. Traffic continues through the VM
   connector to the still-running Fly origin.
4. In Cloudflare Zero Trust, change the tunnel's public hostname
   `api.noticiencias.com` service to `http://localhost:8010`; verify
   `https://api.noticiencias.com/healthz`, a webhook POST, and the admin
   health endpoint (401 without key / 200 with key).
5. Stop (not delete) the Fly serving app as the rollback window
   (`fly machine stop`); destroy both Fly apps after the rollout is
   confirmed.

## Verification

- Local: `curl 127.0.0.1:8010/healthz`, `/readyz`; systemd `active`.
- External: `https://api.noticiencias.com/healthz` 200; webhook POST 202 with
  the shared key; dashboard health endpoint 200 with the admin key; metrics
  bot run continues to read publication/callback/validation evidence.
- Pogo-lab unaffected: `pogo-lab.service`, `nginx`, `postgresql@14-main`,
  and the existing `cloudflared.service` remain active; its hostname still
  serves.
- Fly apps show no running machines after cutover.

## Operations (2026-09-26)

- **Backup:** `noticiencias-backup.timer` (daily 03:45 UTC, 15 min jitter,
  persistent) runs `/opt/noticiencias-serving/bin/backup.sh` — a consistent
  `sqlite3 .backup` snapshot into `/var/backups/noticiencias-serving` with
  14-day retention (mirrors Pogo-lab's convention). First backup verified.
- **Self-healing readiness:** `noticiencias-healthcheck.timer` runs every
  5 minutes; on a failed `http://127.0.0.1:8010/readyz` it logs and restarts
  `noticiencias-serving` (systemd covers crashes; this covers hangs). The
  frontend `bot-health.yml` additionally probes the public `/readyz` daily
  (its failure email is the external alert).
- **Update procedure:**
  1. `rsync` the minimal source set (`config.toml`, `news_collector/`,
     `noticiencias/`, `pyproject.toml`, `README.md`, `LICENSE`) to
     `/opt/noticiencias-serving`.
  2. `ssh`: `cd /opt/noticiencias-serving && ~/.local/bin/uv pip install --python .venv/bin/python .`
  3. `sudo systemctl restart noticiencias-serving`
  4. Verify `curl 127.0.0.1:8010/readyz` and `https://api.noticiencias.com/readyz`.
- Secrets live only in `/etc/noticiencias-serving.env` (root 0600) and the
  tunnel token in `/etc/cloudflared-noticiencias.token`; never in the repo.

## Risks / mitigations

- Shared production VM: additive service, unused port, ~300 MB RAM; Pogo-lab
  has ~10 GB free. Rollback = stop the new unit.
- ARM64 wheels: numpy/scikit-learn/lxml/psycopg all publish aarch64 wheels;
  `uv` resolves them.
- Cloudflare ingress is remotely managed → the hostname edit is a dashboard
  action (the available API token is scoped to tooltician.com only).
- If the local `TUNNEL_TOKEN` is stale, fetch a fresh token from the Zero
  Trust dashboard and set it on the VM only (never commit it).

## Out of scope

- Moving Pogo-lab; changing public hostnames/keys; deleting the Fly apps
  before the rollout is confirmed; OCI micro-VM fallback.
