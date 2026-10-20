/**
 * Bearer-token storage for the admin client.
 *
 * The ADMIN_API_KEY is resolved per request in this order:
 *   1. `localStorage` (operator entered it once via the AuthGate — persists
 *      across restarts).
 *   2. `PUBLIC_ADMIN_API_KEY` build-time env var (seed it in `apps/admin/.env`
 *      to skip the gate entirely).
 *
 * Local dev bypass: under `astro dev` (`import.meta.env.MODE === "development"`)
 * with no `PUBLIC_ADMIN_API_KEY` set, `AUTH_BYPASS` is true — no gate, no Bearer
 * header. This mirrors the serving backend, which fail-opens on an unset
 * ADMIN_API_KEY in the "development" environment (see `verify_admin_token`).
 * Production builds (`MODE === "production"`) and the vitest suite
 * (`MODE === "test"`) always enforce auth.
 *
 * Key rotation (plan 123): the token is a shared bearer secret, not a login.
 * To rotate: (1) set a new ADMIN_API_KEY on the serving backend and restart
 * it; (2) every operator clears the stale token — the AuthGate reappears on
 * the next 401/403 (or clear it manually via `clearToken()` in devtools) —
 * and enters the new key once; (3) if PUBLIC_ADMIN_API_KEY seeds the key,
 * rebuild/redeploy the admin bundle with the new value. There is no expiry
 * or multi-key grace window: during the cutover, requests with the old key
 * get 403 until the operator re-enters the new one. Never commit a real key
 * to `apps/admin/.env` — that file is a local seed, not a vault.
 */

const TOKEN_KEY = 'refinery_admin_token';

const ENV_TOKEN: string | null =
  (import.meta.env.PUBLIC_ADMIN_API_KEY as string | undefined)?.trim() || null;

/**
 * True when the local dev server should skip auth entirely (no gate, no Bearer
 * header). Only in `astro dev` and only when no key was explicitly configured.
 */
export const AUTH_BYPASS: boolean = import.meta.env.MODE === 'development' && ENV_TOKEN === null;

export function getToken(): string | null {
  if (AUTH_BYPASS) return null;
  try {
    const stored = localStorage.getItem(TOKEN_KEY);
    if (stored) return stored;
  } catch {
    /* localStorage unavailable (SSR, privacy mode) — fall through to env */
  }
  return ENV_TOKEN;
}

export function setToken(token: string): void {
  try {
    localStorage.setItem(TOKEN_KEY, token);
  } catch {
    /* localStorage unavailable — token stays in memory for this page only */
  }
}

export function clearToken(): void {
  try {
    localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* nothing to clear */
  }
}
