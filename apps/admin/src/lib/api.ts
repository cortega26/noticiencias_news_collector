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
 */

import type {
  AdminAnalyticsEnvelope,
  AdminArticleDetail,
  AdminArticleListEnvelope,
  AdminBulkResetResult,
  AdminCollectStarted,
  AdminCollectStatus,
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
} from "./types";

const TOKEN_KEY = "refinery_admin_token";

const ENV_TOKEN: string | null =
  (import.meta.env.PUBLIC_ADMIN_API_KEY as string | undefined)?.trim() || null;

/**
 * True when the local dev server should skip auth entirely (no gate, no Bearer
 * header). Only in `astro dev` and only when no key was explicitly configured.
 */
export const AUTH_BYPASS: boolean =
  import.meta.env.MODE === "development" && ENV_TOKEN === null;

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

/**
 * Reveal the AuthGate overlay (rendered by AuthGate.astro) instead of
 * reloading — page scripts call this on AuthError so a missing/expired key
 * lands on the token form without a reload loop.
 */
export function showAuthGate(): void {
  const gate = document.getElementById("auth-gate");
  if (gate) gate.classList.remove("hidden");
}

export class AuthError extends Error {
  constructor(message = "Authentication required") {
    super(message);
    this.name = "AuthError";
  }
}

export class NotFoundError extends Error {
  constructor(message = "Not found") {
    super(message);
    this.name = "NotFoundError";
  }
}

export class ValidationError extends Error {
  constructor(message = "Invalid request") {
    super(message);
    this.name = "ValidationError";
  }
}

/**
 * The serving API could not be reached: `fetch` rejected (DNS/connection
 * refused/CORS) or the dev proxy / a deployment gateway returned 502/503/504
 * because nothing healthy is listening behind it. Almost always "the API is
 * not running" in local dev.
 */
export class NetworkError extends Error {
  constructor(
    message = "Cannot reach the serving API — is it running? Try `make admin`.",
  ) {
    super(message);
    this.name = "NetworkError";
  }
}

/**
 * Thrown on 409 (currently only `/v1/admin/collect`: a collection run is
 * already queued/running). Carries the parsed response body — which is
 * shaped like `AdminCollectStarted` and names the existing run's id — so
 * callers can surface it instead of a bare "HTTP 409".
 */
export class ConflictError<T = unknown> extends Error {
  readonly body: T;
  constructor(body: T, message = "Conflict") {
    super(message);
    this.name = "ConflictError";
    this.body = body;
  }
}

const API_BASE: string = (import.meta.env.PUBLIC_ADMIN_API_BASE as string) ?? "";

async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    ...(init.headers as Record<string, string> | undefined),
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  if (init.body && !(init.body instanceof FormData) && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { ...init, headers });
  } catch {
    throw new NetworkError();
  }

  if (response.status === 401 || response.status === 403) {
    throw new AuthError();
  }
  if (response.status === 404) {
    throw new NotFoundError();
  }
  if (response.status === 422) {
    const body = (await response.json().catch(() => ({}))) as {
      detail?: string;
    };
    throw new ValidationError(body.detail ?? "Invalid request");
  }
  if (response.status === 409) {
    const body = await response.json().catch(() => ({}));
    throw new ConflictError(body, "A conflicting operation is already in progress");
  }
  // 502/503/504 never come from the app itself — it's the dev proxy or a
  // deployment gateway saying nothing healthy answered on :8000.
  if (response.status === 502 || response.status === 503 || response.status === 504) {
    throw new NetworkError(
      `Cannot reach the serving API (HTTP ${response.status}) — is it running? Try \`make admin\`.`,
    );
  }
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return (await response.json()) as T;
}

export function listArticles(
  status: ArticleStatus,
  cursor?: string | null,
  pageSize = 20,
): Promise<AdminArticleListEnvelope> {
  const params = new URLSearchParams({ status, page_size: String(pageSize) });
  if (cursor) params.set("cursor", cursor);
  return apiFetch<AdminArticleListEnvelope>(`/v1/admin/articles?${params}`);
}

export function getArticle(id: number): Promise<AdminArticleDetail> {
  return apiFetch<AdminArticleDetail>(`/v1/admin/articles/${id}`);
}

export function getSourceHealth(): Promise<AdminSourceHealthEnvelope> {
  return apiFetch<AdminSourceHealthEnvelope>(`/v1/admin/sources/health`);
}

export function getAnalytics(): Promise<AdminAnalyticsEnvelope> {
  return apiFetch<AdminAnalyticsEnvelope>(`/v1/admin/analytics`);
}

export function getConfig(): Promise<AdminConfigSnapshot> {
  return apiFetch<AdminConfigSnapshot>(`/v1/admin/config`);
}

export function rejectArticle(
  id: number,
  reason = "",
): Promise<AdminMutationResult> {
  return apiFetch<AdminMutationResult>(`/v1/admin/articles/${id}/reject`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
}

export function updateAuditStatus(
  id: number,
  auditStatus: string,
  reason = "",
): Promise<AdminMutationResult> {
  return apiFetch<AdminMutationResult>(
    `/v1/admin/articles/${id}/audit-status`,
    {
      method: "POST",
      body: JSON.stringify({ audit_status: auditStatus, reason }),
    },
  );
}

export function startCollect(dryRun = false): Promise<AdminCollectStarted> {
  return apiFetch<AdminCollectStarted>("/v1/admin/collect", {
    method: "POST",
    body: JSON.stringify({ dry_run: dryRun }),
  });
}

export function getCollectStatus(
  runId?: string,
): Promise<AdminCollectStatus> {
  const q = runId ? `?run_id=${encodeURIComponent(runId)}` : "";
  return apiFetch<AdminCollectStatus>(`/v1/admin/collect/status${q}`);
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
  return apiFetch<AdminPublishStarted>("/v1/admin/publish", {
    method: "POST",
    body: JSON.stringify({
      article_id: opts.articleId ?? null,
      article_url: opts.articleUrl ?? null,
    }),
  });
}

export function getPublishStatus(
  runId?: string,
): Promise<AdminPublishStatus> {
  const q = runId ? `?run_id=${encodeURIComponent(runId)}` : "";
  return apiFetch<AdminPublishStatus>(`/v1/admin/publish/status${q}`);
}

export function reprocessArticle(id: number): Promise<AdminMutationResult> {
  return apiFetch<AdminMutationResult>(
    `/v1/admin/articles/${id}/reprocess`,
    { method: "POST", body: JSON.stringify({}) },
  );
}

export function listSources(): Promise<{ sources: AdminSourceListItem[] }> {
  return apiFetch<{ sources: AdminSourceListItem[] }>("/v1/admin/sources");
}

export function toggleSource(
  sourceId: string,
  active: boolean,
): Promise<AdminMutationResult> {
  return apiFetch<AdminMutationResult>(
    `/v1/admin/sources/${encodeURIComponent(sourceId)}/toggle`,
    { method: "POST", body: JSON.stringify({ active }) },
  );
}

export function resetSourceCircuit(
  sourceId: string,
): Promise<AdminMutationResult> {
  return apiFetch<AdminMutationResult>(
    `/v1/admin/sources/${encodeURIComponent(sourceId)}/reset`,
    { method: "POST", body: JSON.stringify({}) },
  );
}

export function saveConfig(
  patch: Record<string, unknown>,
): Promise<AdminConfigSnapshot> {
  return apiFetch<AdminConfigSnapshot>("/v1/admin/config", {
    method: "POST",
    body: JSON.stringify(patch),
  });
}

export function getPrompts(): Promise<AdminPromptsEnvelope> {
  return apiFetch<AdminPromptsEnvelope>("/v1/admin/prompts");
}

export function savePrompts(
  prompts: Record<string, Record<string, unknown>>,
): Promise<AdminPromptsEnvelope> {
  return apiFetch<AdminPromptsEnvelope>("/v1/admin/prompts", {
    method: "POST",
    body: JSON.stringify({ prompts }),
  });
}

export function getContent(): Promise<AdminContentEnvelope> {
  return apiFetch<AdminContentEnvelope>("/v1/admin/content");
}

export function getQualityRecent(
  limit = 20,
): Promise<AdminQualityRecentEnvelope> {
  return apiFetch<AdminQualityRecentEnvelope>(
    `/v1/admin/quality/recent?limit=${encodeURIComponent(String(limit))}`,
  );
}

export function getImageQueue(): Promise<{ briefs: AdminImageBriefItem[] }> {
  return apiFetch<{ briefs: AdminImageBriefItem[] }>("/v1/admin/images");
}

export function unpublishArticle(
  refineryId: string,
): Promise<AdminMutationResult> {
  return apiFetch<AdminMutationResult>(
    `/v1/admin/content/${encodeURIComponent(refineryId)}`,
    { method: "DELETE" },
  );
}

export function bulkResetContent(
  refineryIds: string[],
): Promise<AdminBulkResetResult> {
  return apiFetch<AdminBulkResetResult>("/v1/admin/content/bulk-reset", {
    method: "POST",
    body: JSON.stringify({ refinery_ids: refineryIds }),
  });
}

export function updateImageBrief(
  slug: string,
  fields: Record<string, string>,
): Promise<AdminImageBriefUploadResult> {
  return apiFetch<AdminImageBriefUploadResult>(
    `/v1/admin/images/${encodeURIComponent(slug)}`,
    { method: "PUT", body: JSON.stringify(fields) },
  );
}

export function uploadImageBriefAsset(
  slug: string,
  file: File,
  fields: Record<string, string>,
): Promise<AdminImageBriefUploadResult> {
  const form = new FormData();
  form.append("file", file);
  for (const [k, v] of Object.entries(fields)) {
    if (v) form.append(k, v);
  }
  return apiFetch<AdminImageBriefUploadResult>(
    `/v1/admin/images/${encodeURIComponent(slug)}/upload`,
    { method: "POST", body: form },
  );
}

export function deleteSource(sourceId: string): Promise<AdminMutationResult> {
  return apiFetch<AdminMutationResult>(
    `/v1/admin/sources/${encodeURIComponent(sourceId)}`,
    { method: "DELETE" },
  );
}

export function upsertSource(
  payload: AdminSourceUpsertPayload,
): Promise<AdminMutationResult> {
  return apiFetch<AdminMutationResult>("/v1/admin/sources", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
