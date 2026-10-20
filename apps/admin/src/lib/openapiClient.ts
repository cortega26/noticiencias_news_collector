/**
 * Typed `openapi-fetch` client for the admin API.
 *
 * All reads (plan 172) and JSON mutations (plan 173) use this client; the
 * multipart image upload is the only remaining `apiFetch` call in `api.ts`.
 *
 * The middleware reproduces the error taxonomy of `apiFetch` exactly:
 * 401/403 → AuthError, 404 → NotFoundError, 422 → ValidationError,
 * 409 → ConflictError (carrying the parsed body), structured other non-2xx →
 * ApiError, unstructured 502/503/504 → NetworkError, and any other
 * unstructured failure → `Error("HTTP <status>")`. A rejected `fetch` becomes
 * NetworkError. The token is read on every request so a key entered after
 * module load still applies.
 */

import createClient, { type Middleware } from 'openapi-fetch';

import { getToken } from './auth';
import { NetworkError, throwHttpError } from './errors';
import type { paths } from './generated/api';

export const API_BASE: string = (import.meta.env.PUBLIC_ADMIN_API_BASE as string) ?? '';

const adminMiddleware: Middleware = {
  onRequest({ request }) {
    const token = getToken();
    if (token) {
      request.headers.set('Authorization', `Bearer ${token}`);
    }
  },
  async onResponse({ response }) {
    if (!response.ok) await throwHttpError(response);
  },
  onError() {
    return new NetworkError();
  },
};

/**
 * `fetch` is resolved at request time rather than captured when the module
 * loads: tests replace the global per case, and a long-lived page should pick
 * up a patched/polyfilled fetch.
 */
export const client = createClient<paths>({
  baseUrl: API_BASE,
  fetch: (request) => globalThis.fetch(request),
});

client.use(adminMiddleware);
