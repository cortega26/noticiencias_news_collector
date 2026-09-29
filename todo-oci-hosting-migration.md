# Todo: migrate the serving layer from Fly.io to the always-free OCI VM

Execution index for [`spec-oci-hosting-migration.md`](spec-oci-hosting-migration.md).

## Cutover completado (2026-09-26)

- **Ingress cambiado** en Zero Trust (cuenta `7e153214690ac7430fde021f1f2b2916`,
  túnel `noticiencias-webhook` = `5a22de3a-2e80-4c90-9817-ce2ca830c889`):
  `api.noticiencias.com` → `http://localhost:8010`.
- **Verificación inequívoca:** `GET /healthz?m=<epoch>` → 200 y el marcador
  exacto apareció en el journal de `noticiencias-serving` (cliente IPv6 real
  vía Cloudflare); los logs de Fly no recibieron tráfico nuevo.
- **Fly retirado por completo:** `noticiencias-serve` y `noticiencias-tunnel`
  destruidos; `fly apps list` → "No apps found"; la API pública siguió en 200
  tras destruir la máquina (100 % OCI).
- **Lección registrada:** una verificación previa pareció exitosa por una
  ventana de tiempo solapada con un curl local; la verificación válida exige
  un marcador único en el journal del servicio de la VM. Además, el primer
  intento de cambio se hizo desde otra cuenta de Cloudflare (sin túneles);
  el túnel vive en la cuenta de noticiencias indicada arriba.
- **Rollback ya no aplica** (Fly destruido); el rollback vigente es detener
  `noticiencias-serving.service` y volver a desplegar Fly desde el repo
  (`fly deploy --config fly-serving.toml` + secretos) si fuese necesario.

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

- [x] Zero Trust (cuenta `7e153214690ac7430fde021f1f2b2916`) → Networks →
      Tunnels → `noticiencias-webhook` (ID
      `5a22de3a-2e80-4c90-9817-ce2ca830c889`) → Public Hostnames →
      `api.noticiencias.com` → Edit → Service = `http://localhost:8010` → Save.
- [x] Verify externally with a unique marker: `/healthz?m=<epoch>` → 200 and
      the exact marker in the VM journal; webhook POST with the shared key →
      422 on an empty payload (auth OK); `/v1/admin/dashboard/health` with the
      admin key → 200. (The scheduled metrics run exercises the same endpoint.)

## Step 4 — retire Fly

- [x] `fly scale count 0 -a noticiencias-serve`, public 200 ×3 after the
      machine was destroyed, then `fly apps destroy noticiencias-serve` and
      `fly apps destroy noticiencias-tunnel`.
- [x] `fly apps list` → "No apps found"; compute billing drops to $0.

## Follow-ups

- [x] OCI-hosted deploy/update procedure documented (spec §Operations:
      rsync + `uv pip install .` + restart + verify).
- [x] Health monitor/alert: local `noticiencias-healthcheck.timer` (5 min,
      restarts on a hung `/readyz`) + daily public readiness probe in the
      frontend `bot-health.yml` (GitHub failure email is the alert).
- [x] Backup: `noticiencias-backup.timer` (daily 03:45 UTC, 14-day
      retention, consistent `sqlite3 .backup`); first backup verified at
      `/var/backups/noticiencias-serving`.
- [ ] Optional: copy backups off the VM (same open P0 as Pogo-lab's own
      backup durability item).
- [x] Pogo-lab prod remains untouched: `pogo-lab.service`, `nginx`,
      `postgresql@14-main`, `reddit-monitor-web.service`, and the existing
      `cloudflared.service` stay active.
