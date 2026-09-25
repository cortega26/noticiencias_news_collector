# Todo: migrate the serving layer from Fly.io to the always-free OCI VM

Execution index for [`spec-oci-hosting-migration.md`](spec-oci-hosting-migration.md).

## Pendiente para mañana (2026-09-26)

1. **Cloudflare (manual, ~1 min):** Zero Trust → Networks → Tunnels →
   `noticiencias-webhook` (ID `5a22de3a-2e80-4c90-9817-ce2ca830c889`) →
   Public Hostnames → `api.noticiencias.com` → Edit → Service =
   `http://localhost:8010` → Save.
2. **Verificar el corte:** `https://api.noticiencias.com/healthz` → 200;
   webhook POST con la key compartida → 202; `/v1/admin/dashboard/health` con
   la key admin → 200; el siguiente run del bot de métricas debe seguir
   leyendo la evidencia del backend (publication/callbacks/validation).
3. **Retirar Fly:** `fly scale count 0 -a noticiencias-serve`, verificar de
   nuevo, y después `fly apps destroy noticiencias-serve noticiencias-tunnel`.
4. **Rollback en cualquier punto previo al paso 3:**
   `fly scale count 1 -a noticiencias-tunnel` (la config de la app se
   conserva; solo se destruyó la máquina).

## Step 1 — deploy the serving app on the VM

- [x] Source rsynced to `/opt/noticiencias-serving` (minimal copy, no `.git`/`data`).
- [x] Python 3.13 venv via `uv`; `uv pip install .` (11 s, aarch64 wheels only).
- [x] `/etc/noticiencias-serving.env` (root 0600) with
      `NOTICIENCIAS__APP__ENVIRONMENT=production`, `WEBHOOK_API_KEY`,
      `ADMIN_API_KEY` reused from Fly (secrets never committed).
- [x] `noticiencias-serving.service` enabled/running on `127.0.0.1:8010`
      (Pogo-lab keeps :8000).
- [x] Local checks: `healthz=200`, `readyz=200`, admin 401 without key /
      200 with key, webhook wrong key 403.

## Step 2 — tunnel connector on the VM

- [x] Local `TUNNEL_TOKEN` validated (`tunnelID=5a22de3a-2e80-4c90-9817-ce2ca830c889`).
- [x] `cloudflared-noticiencias.service` enabled/running
      (`--token-file /etc/cloudflared-noticiencias.token`, root 0600).
- [x] Fly tunnel connector retired: `fly scale count 0 -a noticiencias-tunnel`
      (machine destroyed; app config kept for rollback).
- [x] Public verification with the VM connector serving and the tunnel still
      pointing at the Fly origin: `https://api.noticiencias.com/healthz` → 200,
      admin → 401, three consecutive attempts.

## Step 3 — switch the tunnel ingress (needs Cloudflare dashboard)

- [ ] Zero Trust → Networks → Tunnels → `noticiencias-webhook`
      (ID `5a22de3a-2e80-4c90-9817-ce2ca830c889`) → Public Hostnames →
      `api.noticiencias.com` → Edit → Service = `http://localhost:8010` → Save.
- [ ] Verify externally: `/healthz` 200; webhook POST with the shared key →
      202/accepted; `/v1/admin/dashboard/health` with the admin key → 200;
      dashboard health still reads backend evidence on the next metrics run.

## Step 4 — retire Fly

- [ ] After the cutover is confirmed: `fly scale count 0 -a noticiencias-serve`
      (rollback window), then `fly apps destroy noticiencias-serve` and
      `fly apps destroy noticiencias-tunnel`.
- [ ] Confirm `fly apps list` shows neither app running; billing drops to $0.

## Follow-ups

- [ ] Add OCI-hosted deploy/update procedure (rsync + `uv pip install .` +
      `systemctl restart`) to the spec or a runbook.
- [ ] Consider a lightweight health monitor/alert for
      `noticiencias-serving.service` (Pogo-lab has its own alerts only).
- [ ] Pogo-lab prod remains untouched: `pogo-lab.service`, `nginx`,
      `postgresql@14-main`, `reddit-monitor-web.service`, and the existing
      `cloudflared.service` stay active.
