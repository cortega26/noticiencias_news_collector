# TODO — deploy + rechequeo del webhook inbox pull (ADR-0011)

> Handoff para retomar tras reiniciar el editor. Estado al 2026-09-30.
> Retomar con: "seguí `todo-webhook-inbox-deploy.md`".

## Estado actual (ya hecho, no rehacer)

- **Código mergeado en `main`** (`04016ca`): PRs #358 (SERVING_RELOAD),
  #359 (progreso en vivo), #360 (ADR-0011), #361 (inbox + puller).
- **2671**: publicado en vivo (https://noticiencias.com/ciencia/2026-09-25-la-gravedad-como-proyector-holografico-del-universo/),
  PR frontend #231 mergeado, deploy OK; reconciliado en la BD local con el
  replay `id:v1:36785713548:publish_complete` (intento 16 → COMPLETED).
- **Verificado**: CI del PR #361 100% verde (incl. Codacy), `make test` 3516,
  ratchet 93.04%, contracts/boundaries/admin/docs/inventory verdes, 20 tests
  nuevos del inbox. `admin_stack.sh` con sintaxis OK.
- **NO desplegado**: `https://api.noticiencias.com/v1/admin/webhook/receipts`
  responde **404** — la VM OCI corre el código anterior. Es esperado.
- **Falta config local**: `.env` solo tiene `WEBHOOK_API_KEY`; no hay
  `ADMIN_API_KEY` ni `BACKEND_ADMIN_URL`/`BACKEND_WEBHOOK_URL`.
- `data/exports/latest_articles.json` sigue sin commitear (artefacto de runtime).

## Paso 1 — Desplegar el serving en la VM OCI

Procedimiento exacto en `spec-oci-hosting-migration.md` §"Update procedure"
(source en `/opt/noticiencias-serving`, env en
`/etc/noticiencias-serving.env`, SQLite en
`/opt/noticiencias-serving/data/news_v3.db`):

1. `rsync` del set mínimo (`config.toml`, `news_collector/`, `noticiencias/`,
   `pyproject.toml`, `README.md`, `LICENSE`) a `/opt/noticiencias-serving`.
2. En la VM: `cd /opt/noticiencias-serving && ~/.local/bin/uv pip install --python .venv/bin/python .`
3. `sudo systemctl restart noticiencias-serving`
4. Verificar `curl 127.0.0.1:8010/readyz` y `https://api.noticiencias.com/readyz`.

Comprobación del endpoint nuevo:

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://api.noticiencias.com/v1/admin/webhook/receipts
```

- **Esperado: 401** (existe y pide Bearer) o **503** (existe pero sin
  `ADMIN_API_KEY` en el env de producción — revisar `/etc/noticiencias-serving.env`).
- **404 = todavía no desplegado** (estado actual).

## Paso 2 — Config local (secretos del operador, no van al repo)

En `.env`:

```
ADMIN_API_KEY=<la misma que /etc/noticiencias-serving.env>
BACKEND_ADMIN_URL=https://api.noticiencias.com
```

(Alternativa: con `BACKEND_WEBHOOK_URL` ya seteado, el puller deriva el
origin solo.)

## Paso 3 — Smoke del pull

```bash
make webhooks-pull ARGS="--dry-run"   # no escribe; reporta qué haría
make webhooks-pull                    # aplica (idempotente por delivery key)
make webhooks-pull                    # 2ª corrida: todo duplicates
```

Esperado en dry-run: `fetched=N`, `replayed=N`, `duplicates=0`,
`malformed=0` y `dry-run: no rows were written`. En la corrida real, el
receipt histórico `id:v1:36785713548:publish_complete` debe caer como
**duplicate** (ya se aplicó el replay manual del 2671).

## Paso 4 — Opcional (dejarlo invisible)

- `WEBHOOK_INBOX_PULL=1 make admin` → pull best-effort al arrancar (ver el
  log `[admin-stack] pulling pending webhook receipts…`).
- Timer systemd cada 15 min corriendo
  `scripts/ops/pull_webhook_receipts.py` (documentado en
  `docs/RUNBOOK_LOCAL_DEV.md` §"Webhook callbacks").

## Criterios de aceptación (marcar al rechequear)

- [x] `https://api.noticiencias.com/v1/admin/webhook/receipts` responde 401/503 (ya no 404) — 401 verificado 2026-10-26
- [ ] `make webhooks-pull ARGS="--dry-run"` corre contra el hosted y reporta sin escribir
- [ ] `make webhooks-pull` aplica y una segunda corrida es 100% duplicates
- [ ] `WEBHOOK_INBOX_PULL=1 make admin` ejecuta el pull al arrancar (log visible)
- [ ] Un publish local nuevo queda `completed` tras el pull, sin replay manual
- [x] (Opcional) timer systemd instalado y corriendo — `noticiencias-webhooks-pull.timer` cada 15 min (usuario)

## Follow-ups conocidos (no bloquean)

- Política de retención/prune de receipts en la VM (hoy crecen sin límite) —
  anotada en `spec-webhook-inbox-pull.md` §Risks.
- ¿Registrar el timer systemd en el runbook como paso operativo estándar?

## Referencias

- `docs/adr/0011-local-publish-hosted-webhook-split.md` (decisión aceptada)
- `spec-webhook-inbox-pull.md` / `todo-webhook-inbox-pull.md` (spec del inbox)
- `spec-oci-hosting-migration.md` §Operations (deploy/update de la VM)
- `docs/RUNBOOK_LOCAL_DEV.md` §"Webhook callbacks (hosted inbox → local pull)"

## Rechequeo 2026-10-26

- El timer ejecutaba una copia del código del 2026-10-10 sin la corrección del
  plan 132; un recibo no correlacionado bloqueó la cola desde el 2026-10-19.
  Ahora usa una copia de `main` (`~/.local/share/noticiencias-serving-<sha>`,
  drop-in `90-noticiencias-runtime.conf`); regenerarla tras cada cambio del
  puller.
- Los callbacks perdidos o sin correlación se cierran con
  `scripts/ops/reconcile_publication_attempts.py --github` (plan 198).
- Pendiente: las verificaciones de `make webhooks-pull` manual y
  `WEBHOOK_INBOX_PULL=1 make admin` (requieren `ADMIN_API_KEY` local).
