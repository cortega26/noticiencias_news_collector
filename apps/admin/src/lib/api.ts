/**
 * Typed fetch client for the Phase-1 admin API (`/v1/admin/*`).
 *
 * Auth: the ADMIN_API_KEY is attached as a Bearer header on every request and
 * resolved in this order:
 *   1. `localStorage` (operator entered it once via the AuthGate — persists
 *      across restarts, unlike the previous sessionStorage).
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
 * 401/403 surfaces as AuthError so the UI can drop back to the token gate.
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

import { getToken } from './auth';
import { NetworkError, mapOpenApiError, throwHttpError } from './errors';
import { API_BASE, client } from './openapiClient';
import type { components } from './generated/api';
import type {
  AdminAnalyticsEnvelope,
  AdminArticleDetail,
  AdminArticleListEnvelope,
  AdminBulkResetResult,
  AdminCollectStarted,
  AdminCollectStatus,
  AdminPublishBatchStarted,
  AdminPublishStarted,
  AdminPublishStatus,
  AdminConfigSnapshot,
  AdminContentEnvelope,
  AdminImageBriefItem,
  AdminImageBriefUploadResult,
  AdminMutationResult,
  AdminPromptsEnvelope,
  AdminQualityRecentEnvelope,
  AdminSourceHealthEnvelope,
  AdminSourceListItem,
  AdminSourceUpsertPayload,
  ArticleStatus,
} from './types';

export { AUTH_BYPASS, clearToken, getToken, setToken } from './auth';
export {
  ApiError,
  AuthError,
  ConflictError,
  NetworkError,
  NotFoundError,
  ValidationError,
} from './errors';

/**
 * Reveal the AuthGate overlay (rendered by AuthGate.astro) instead of
 * reloading — page scripts call this on AuthError so a missing/expired key
 * lands on the token form without a reload loop.
 */
export function showAuthGate(): void {
  const gate = document.getElementById('auth-gate');
  if (gate) gate.classList.remove('hidden');
}

async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    ...(init.headers as Record<string, string> | undefined),
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  if (init.body && !(init.body instanceof FormData) && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json';
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { ...init, headers });
  } catch {
    throw new NetworkError();
  }

  if (!response.ok) {
    await throwHttpError(response);
  }
  return (await response.json()) as T;
}

/**
 * Run a typed GET and narrow the generated payload to the hand-written
 * contract. The generated schemas mark server-defaulted fields optional and
 * widen some nested records (`source`, list envelopes); the runtime wire shape
 * is still the `Admin*` model from `news_collector/contracts/admin.py`. This is
 * the same narrow cast `getArticle` uses — never `any`.
 */
async function readContract<T>(
  request: Promise<{ data?: unknown; error?: unknown; response: Response }>
): Promise<T> {
  const { data, error, response } = await request;
  if (error) throw mapOpenApiError(error, response);
  return data as T;
}

/**
 * Run a typed JSON mutation and narrow the generated payload to the
 * hand-written contract, exactly like {@link readContract}. The generated
 * schemas mark server-defaulted fields optional (for example
 * `AdminBulkResetResult.failed`), while the runtime wire is the `Admin*` model
 * from `news_collector/contracts/admin.py`.
 *
 * The client's `onResponse` middleware throws the shared error taxonomy first
 * (409 → `ConflictError` with the parsed body, 422 → `ValidationError`,
 * 401/403 → `AuthError`), so the `error` branch is a defensive fallback for
 * any request configured without that middleware.
 */
async function mutationContract<T>(
  request: Promise<{ data?: unknown; error?: unknown; response: Response }>
): Promise<T> {
  const { data, error, response } = await request;
  if (error) throw mapOpenApiError(error, response);
  return data as T;
}

export function listArticles(
  status: ArticleStatus,
  cursor?: string | null,
  pageSize = 20
): Promise<AdminArticleListEnvelope> {
  return readContract<AdminArticleListEnvelope>(
    client.GET('/v1/admin/articles', {
      params: {
        query: {
          status,
          page_size: pageSize,
          // `apiFetch` omitted an empty cursor; keep that wire behavior.
          cursor: cursor || undefined,
        },
      },
    })
  );
}

export async function getArticle(id: number): Promise<AdminArticleDetail> {
  const { data, error, response } = await client.GET('/v1/admin/articles/{article_id}', {
    params: { path: { article_id: id } },
  });
  if (error) throw mapOpenApiError(error, response);
  // The generated schema is looser than the handwritten contract (for example
  // `source` is `Record<string, unknown>` instead of `{id, name}`); the wire
  // shape is the same `AdminArticleDetail` from `news_collector/contracts/admin.py`.
  return data as unknown as AdminArticleDetail;
}

export function getSourceHealth(): Promise<AdminSourceHealthEnvelope> {
  return readContract<AdminSourceHealthEnvelope>(client.GET('/v1/admin/sources/health'));
}

export function getAnalytics(): Promise<AdminAnalyticsEnvelope> {
  return readContract<AdminAnalyticsEnvelope>(client.GET('/v1/admin/analytics'));
}

export function getConfig(): Promise<AdminConfigSnapshot> {
  return readContract<AdminConfigSnapshot>(client.GET('/v1/admin/config'));
}

export function rejectArticle(id: number, reason = ''): Promise<AdminMutationResult> {
  return mutationContract<AdminMutationResult>(
    client.POST('/v1/admin/articles/{article_id}/reject', {
      params: { path: { article_id: id } },
      body: { reason },
    })
  );
}

export function updateAuditStatus(
  id: number,
  auditStatus: string,
  reason = ''
): Promise<AdminMutationResult> {
  return mutationContract<AdminMutationResult>(
    client.POST('/v1/admin/articles/{article_id}/audit-status', {
      params: { path: { article_id: id } },
      body: { audit_status: auditStatus, reason },
    })
  );
}

export function startCollect(dryRun = false): Promise<AdminCollectStarted> {
  return mutationContract<AdminCollectStarted>(
    client.POST('/v1/admin/collect', { body: { dry_run: dryRun } })
  );
}

export function getCollectStatus(runId?: string): Promise<AdminCollectStatus> {
  return readContract<AdminCollectStatus>(
    client.GET('/v1/admin/collect/status', {
      params: {
        // `apiFetch` omitted an empty run_id; keep that wire behavior.
        query: { run_id: runId || undefined },
      },
    })
  );
}

/**
 * Start one "Refine & Publish" run — pass exactly one of `articleId`
 * (must be in the current export shortlist) or `articleUrl`. 409 →
 * ConflictError carrying the active run's id; 422 → ValidationError.
 */
export function startPublish(opts: {
  articleId?: number;
  articleUrl?: string;
}): Promise<AdminPublishStarted> {
  return mutationContract<AdminPublishStarted>(
    client.POST('/v1/admin/publish', {
      body: {
        article_id: opts.articleId ?? null,
        article_url: opts.articleUrl ?? null,
      },
    })
  );
}

export function getPublishStatus(runId?: string): Promise<AdminPublishStatus> {
  return readContract<AdminPublishStatus>(
    client.GET('/v1/admin/publish/status', {
      params: {
        // `apiFetch` omitted an empty run_id; keep that wire behavior.
        query: { run_id: runId || undefined },
      },
    })
  );
}

/**
 * Start one batch "Refine & Publish" run for 1..5 article ids — refined
 * sequentially in a single slot, each id getting an explicit per-item
 * outcome in the run summary. 409 → ConflictError; 422 → ValidationError.
 */
export function startPublishBatch(articleIds: number[]): Promise<AdminPublishBatchStarted> {
  return mutationContract<AdminPublishBatchStarted>(
    client.POST('/v1/admin/publish/batch', { body: { article_ids: articleIds } })
  );
}

export function reprocessArticle(id: number): Promise<AdminMutationResult> {
  return mutationContract<AdminMutationResult>(
    client.POST('/v1/admin/articles/{article_id}/reprocess', {
      params: { path: { article_id: id } },
      // The generated spec declares no request body; the existing wire sends
      // `{}`, so cast only the body and keep the bytes identical.
      body: {} as never,
    })
  );
}

export function listSources(): Promise<{ sources: AdminSourceListItem[] }> {
  return readContract<{ sources: AdminSourceListItem[] }>(client.GET('/v1/admin/sources'));
}

export function toggleSource(sourceId: string, active: boolean): Promise<AdminMutationResult> {
  return mutationContract<AdminMutationResult>(
    client.POST('/v1/admin/sources/{source_id}/toggle', {
      params: { path: { source_id: sourceId } },
      body: { active },
    })
  );
}

export function resetSourceCircuit(sourceId: string): Promise<AdminMutationResult> {
  return mutationContract<AdminMutationResult>(
    client.POST('/v1/admin/sources/{source_id}/reset', {
      params: { path: { source_id: sourceId } },
      // The generated spec declares no request body; the existing wire sends
      // `{}`, so cast only the body and keep the bytes identical.
      body: {} as never,
    })
  );
}

export function saveConfig(patch: Record<string, unknown>): Promise<AdminConfigSnapshot> {
  return mutationContract<AdminConfigSnapshot>(client.POST('/v1/admin/config', { body: patch }));
}

export function getPrompts(): Promise<AdminPromptsEnvelope> {
  return readContract<AdminPromptsEnvelope>(client.GET('/v1/admin/prompts'));
}

export function savePrompts(
  prompts: Record<string, Record<string, unknown>>
): Promise<AdminPromptsEnvelope> {
  return mutationContract<AdminPromptsEnvelope>(
    client.POST('/v1/admin/prompts', { body: { prompts } })
  );
}

export function getContent(): Promise<AdminContentEnvelope> {
  return readContract<AdminContentEnvelope>(client.GET('/v1/admin/content'));
}

export function getQualityRecent(limit = 20): Promise<AdminQualityRecentEnvelope> {
  return readContract<AdminQualityRecentEnvelope>(
    client.GET('/v1/admin/quality/recent', { params: { query: { limit } } })
  );
}

export function getImageQueue(): Promise<{ briefs: AdminImageBriefItem[] }> {
  return readContract<{ briefs: AdminImageBriefItem[] }>(client.GET('/v1/admin/images'));
}

export function unpublishArticle(refineryId: string): Promise<AdminMutationResult> {
  return mutationContract<AdminMutationResult>(
    client.DELETE('/v1/admin/content/{refinery_id}', {
      params: { path: { refinery_id: refineryId } },
    })
  );
}

export function bulkResetContent(refineryIds: string[]): Promise<AdminBulkResetResult> {
  return mutationContract<AdminBulkResetResult>(
    client.POST('/v1/admin/content/bulk-reset', { body: { refinery_ids: refineryIds } })
  );
}

export function updateImageBrief(
  slug: string,
  fields: Record<string, string>
): Promise<AdminImageBriefUploadResult> {
  return mutationContract<AdminImageBriefUploadResult>(
    client.PUT('/v1/admin/images/{slug}', {
      params: { path: { slug } },
      // The generated schema lists the brief's editable fields as a closed
      // shape, while this function accepts an arbitrary string map. Cast only
      // the body so every caller field reaches the wire unchanged.
      body: fields as unknown as components['schemas']['AdminImageBriefUpdate'],
    })
  );
}

/**
 * The one deliberate exception to the typed client: this endpoint sends
 * `multipart/form-data` (a `File` part plus optional text fields). `apiFetch`
 * already serializes that wire correctly, so it stays on the hand-written
 * client until a FormData-aware typed serializer is scoped.
 */
export function uploadImageBriefAsset(
  slug: string,
  file: File,
  fields: Record<string, string>
): Promise<AdminImageBriefUploadResult> {
  const form = new FormData();
  form.append('file', file);
  for (const [k, v] of Object.entries(fields)) {
    if (v) form.append(k, v);
  }
  return apiFetch<AdminImageBriefUploadResult>(
    `/v1/admin/images/${encodeURIComponent(slug)}/upload`,
    { method: 'POST', body: form }
  );
}

export function deleteSource(sourceId: string): Promise<AdminMutationResult> {
  return mutationContract<AdminMutationResult>(
    client.DELETE('/v1/admin/sources/{source_id}', {
      params: { path: { source_id: sourceId } },
    })
  );
}

export function upsertSource(payload: AdminSourceUpsertPayload): Promise<AdminMutationResult> {
  return mutationContract<AdminMutationResult>(
    client.POST('/v1/admin/sources', {
      // The editor payload keeps category/update_frequency/group as free-form
      // strings; the generated schema narrows them to their allowed literals.
      // Cast only the body so the wire stays exactly the caller's object.
      body: payload as unknown as components['schemas']['AdminSourceUpsert'],
    })
  );
}
