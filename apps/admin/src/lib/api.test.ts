/**
 * Vitest suite for the admin API client. Uses a stubbed global fetch so no
 * backend is required.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  AUTH_BYPASS,
  AuthError,
  ConflictError,
  NetworkError,
  NotFoundError,
  ValidationError,
  clearToken,
  getAnalytics,
  getArticle,
  getCollectStatus,
  getConfig,
  getContent,
  getImageQueue,
  getPrompts,
  getSourceHealth,
  getToken,
  listArticles,
  rejectArticle,
  bulkResetContent,
  deleteSource,
  reprocessArticle,
  resetSourceCircuit,
  saveConfig,
  savePrompts,
  setToken,
  startCollect,
  startPublish,
  getPublishStatus,
  toggleSource,
  unpublishArticle,
  upsertSource,
  updateAuditStatus,
  updateImageBrief,
  uploadImageBriefAsset,
} from "./api";
import type { AdminArticleListEnvelope } from "./types";

class MemoryStorage implements Storage {
  private store = new Map<string, string>();
  get length(): number {
    return this.store.size;
  }
  clear(): void {
    this.store.clear();
  }
  getItem(key: string): string | null {
    return this.store.get(key) ?? null;
  }
  key(index: number): string | null {
    return [...this.store.keys()][index] ?? null;
  }
  removeItem(key: string): void {
    this.store.delete(key);
  }
  setItem(key: string, value: string): void {
    this.store.set(key, value);
  }
}

vi.stubGlobal("localStorage", new MemoryStorage());

const envelope: AdminArticleListEnvelope = {
  data: [
    {
      id: 1,
      title: "CRISPR gene therapy milestone",
      summary: "Breakthrough",
      url: "https://example.com/1",
      source: { id: "nature", name: "Nature" },
      category: "science",
      topics: ["science"],
      published_at: null,
      collected_at: "2026-08-13T10:00:00Z",
      final_score: 0.92,
      score_components: { source_credibility: 0.95 },
      why_ranked: ["Fuente altamente confiable"],
      processing_status: "pending",
      error_message: null,
      published_url: null,
      refinery_id: "refinery-1",
      publishable: true,
      export_score: 0.92,
    },
  ],
  pagination: { next_cursor: null, has_more: false, page_size: 20, returned: 1 },
  filters: { status: "pending", source: [] },
  meta: { generated_at: "2026-08-13T10:00:00Z" },
};

function mockFetchResponse(status: number, body: unknown): void {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
}

function mockFetchReject(): void {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
  );
}

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("token helpers", () => {
  it("persists and clears the token in localStorage", () => {
    expect(getToken()).toBeNull();
    setToken("admin-key");
    expect(getToken()).toBe("admin-key");
    expect(localStorage.getItem("refinery_admin_token")).toBe("admin-key");
    clearToken();
    expect(getToken()).toBeNull();
  });

  it("does not bypass auth outside the dev server (MODE=test)", () => {
    expect(AUTH_BYPASS).toBe(false);
    expect(getToken()).toBeNull();
  });
});

describe("listArticles", () => {
  it("sends the Bearer token and status filter", async () => {
    setToken("admin-key");
    mockFetchResponse(200, envelope);

    const result = await listArticles("pending");

    expect(result.data).toHaveLength(1);
    expect(result.data[0].title).toBe("CRISPR gene therapy milestone");
    const fetchMock = vi.mocked(fetch);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("status=pending");
    expect((init.headers as Record<string, string>).Authorization).toBe(
      "Bearer admin-key",
    );
  });

  it("appends the cursor when provided", async () => {
    setToken("admin-key");
    mockFetchResponse(200, envelope);

    await listArticles("pending", "abc123");

    const fetchMock = vi.mocked(fetch);
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("cursor=abc123");
  });

  it("throws AuthError on 401", async () => {
    mockFetchResponse(401, { detail: "Missing Authorization header" });
    await expect(listArticles("pending")).rejects.toBeInstanceOf(AuthError);
  });

  it("throws AuthError on 403", async () => {
    mockFetchResponse(403, { detail: "Invalid admin API key" });
    await expect(listArticles("pending")).rejects.toBeInstanceOf(AuthError);
  });

  it("throws NotFoundError on 404", async () => {
    mockFetchResponse(404, { detail: "Article not found" });
    await expect(listArticles("pending")).rejects.toBeInstanceOf(NotFoundError);
  });

  it("throws ValidationError on 422", async () => {
    mockFetchResponse(422, { detail: "Invalid status 'bogus'" });
    const err = await listArticles("pending").catch((e) => e);
    expect(err).toBeInstanceOf(ValidationError);
    expect((err as ValidationError).message).toContain("bogus");
  });

  it("throws NetworkError when fetch rejects", async () => {
    mockFetchReject();
    await expect(listArticles("pending")).rejects.toBeInstanceOf(NetworkError);
  });

  it.each([502, 503, 504])(
    "maps gateway status %i to a NetworkError that names the fix",
    async (status) => {
      mockFetchResponse(status, "");
      const err = await listArticles("pending").catch((e) => e);
      expect(err).toBeInstanceOf(NetworkError);
      expect((err as NetworkError).message).toContain("serving API");
      expect((err as NetworkError).message).toContain("make admin");
    },
  );

  it("still reports other 5xx as a bare HTTP error", async () => {
    mockFetchResponse(500, { detail: "boom" });
    const err = await listArticles("pending").catch((e) => e);
    expect(err).not.toBeInstanceOf(NetworkError);
    expect((err as Error).message).toBe("HTTP 500");
  });
});

describe("mutation endpoints", () => {
  it("rejectArticle POSTs the reason", async () => {
    setToken("admin-key");
    mockFetchResponse(200, {
      status: "ok",
      detail: "Rejected publication attempt refinery-1",
      updated: 1,
    });

    const result = await rejectArticle(1, "duplicate");

    expect(result.status).toBe("ok");
    const fetchMock = vi.mocked(fetch);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/v1/admin/articles/1/reject");
    expect((init as RequestInit).method).toBe("POST");
    expect(JSON.parse(String((init as RequestInit).body))).toEqual({
      reason: "duplicate",
    });
  });

  it("updateAuditStatus POSTs audit_status", async () => {
    setToken("admin-key");
    mockFetchResponse(200, {
      status: "ok",
      detail: "Audit status 'failed' recorded",
      updated: 1,
    });

    await updateAuditStatus(7, "failed", "low signal");

    const fetchMock = vi.mocked(fetch);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/v1/admin/articles/7/audit-status");
    expect(JSON.parse(String((init as RequestInit).body))).toEqual({
      audit_status: "failed",
      reason: "low signal",
    });
  });
});

describe("read endpoints", () => {
  it("getArticle requests the detail path", async () => {
    mockFetchResponse(200, { id: 1, title: "x" });
    await getArticle(1);
    const fetchMock = vi.mocked(fetch);
    expect(fetchMock.mock.calls[0][0]).toBe("/v1/admin/articles/1");
  });

  it("getSourceHealth / getAnalytics / getConfig hit their paths", async () => {
    const paths: string[] = [];
    const fetchSpy = vi.fn(async (input: RequestInfo | URL) => {
      paths.push(String(input));
      return new Response("{}", {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fetchSpy);

    await getSourceHealth();
    await getAnalytics();
    await getConfig();

    expect(paths).toContain("/v1/admin/sources/health");
    expect(paths).toContain("/v1/admin/analytics");
    expect(paths).toContain("/v1/admin/config");
  });
});

describe("phase 3 operational client", () => {
  it("startCollect POSTs dry_run", async () => {
    setToken("admin-key");
    mockFetchResponse(200, {
      run_id: "collect-1",
      status: "queued",
      detail: "Collection started (dry-run)",
    });

    const started = await startCollect(true);

    expect(started.run_id).toBe("collect-1");
    const fetchMock = vi.mocked(fetch);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/v1/admin/collect");
    expect(JSON.parse(String(init.body))).toEqual({ dry_run: true });
  });

  it("startCollect throws ConflictError with the existing run's body on 409", async () => {
    mockFetchResponse(409, {
      run_id: "collect-1",
      status: "running",
      detail: "A collection run is already queued or running.",
    });

    const err = await startCollect(false).catch((e) => e);

    expect(err).toBeInstanceOf(ConflictError);
    expect((err as ConflictError).body).toMatchObject({ run_id: "collect-1" });
  });

  it("getCollectStatus hits the status path with run_id", async () => {
    mockFetchResponse(200, {
      run_id: "collect-1",
      status: "running",
      started_at: "now",
      finished_at: null,
      error: null,
      summary: {},
      active: true,
    });

    await getCollectStatus("collect-1");

    const fetchMock = vi.mocked(fetch);
    expect(String(fetchMock.mock.calls[0][0])).toContain(
      "/v1/admin/collect/status?run_id=collect-1",
    );
  });

  it("startPublish POSTs article_id (url null)", async () => {
    mockFetchResponse(202, { run_id: "7", status: "queued", detail: "Publication started." });

    await startPublish({ articleId: 42 });

    const [url, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/v1/admin/publish");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({
      article_id: 42,
      article_url: null,
      dry_run: false,
    });
  });

  it("startPublish POSTs article_url (id null)", async () => {
    mockFetchResponse(202, { run_id: "8", status: "queued", detail: "Publication started." });

    await startPublish({ articleUrl: "https://example.com/x" });

    const [, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({
      article_id: null,
      article_url: "https://example.com/x",
      dry_run: false,
    });
  });

  it("startPublish surfaces a 409 as ConflictError carrying the active run id", async () => {
    mockFetchResponse(409, { run_id: "5", status: "running", detail: "A publication run is already queued or running." });

    const err = await startPublish({ articleId: 1 }).catch((e) => e);

    expect(err).toBeInstanceOf(ConflictError);
    expect((err as ConflictError).body).toMatchObject({ run_id: "5" });
  });

  it("startPublish maps a proxy 502 to NetworkError", async () => {
    mockFetchResponse(502, "");
    await expect(startPublish({ articleId: 1 })).rejects.toBeInstanceOf(NetworkError);
  });

  it("getPublishStatus hits the status path with run_id", async () => {
    mockFetchResponse(200, {
      run_id: "7",
      status: "succeeded",
      started_at: "now",
      finished_at: "later",
      error: null,
      summary: { pr_url: "https://github.com/x/y/pull/9" },
      active: false,
      pr_url: "https://github.com/x/y/pull/9",
      failure_class: null,
      final_slug: "gene-therapy",
    });

    const st = await getPublishStatus("7");

    expect(String(vi.mocked(fetch).mock.calls[0][0])).toContain(
      "/v1/admin/publish/status?run_id=7",
    );
    expect(st.pr_url).toBe("https://github.com/x/y/pull/9");
  });

  it("reprocessArticle / toggleSource / resetSourceCircuit POST correctly", async () => {
    mockFetchResponse(200, { status: "ok", detail: "ok", updated: 1 });
    await reprocessArticle(5);
    let fetchMock = vi.mocked(fetch);
    expect(String(fetchMock.mock.calls[0][0])).toBe(
      "/v1/admin/articles/5/reprocess",
    );

    mockFetchResponse(200, { status: "ok", detail: "ok", updated: 1 });
    await toggleSource("nature", false);
    fetchMock = vi.mocked(fetch);
    expect(String(fetchMock.mock.calls[0][0])).toBe(
      "/v1/admin/sources/nature/toggle",
    );

    mockFetchResponse(200, { status: "ok", detail: "ok", updated: 1 });
    await resetSourceCircuit("nature");
    fetchMock = vi.mocked(fetch);
    expect(String(fetchMock.mock.calls[0][0])).toBe(
      "/v1/admin/sources/nature/reset",
    );
  });

  it("saveConfig / getPrompts / savePrompts / getContent / getImageQueue hit paths", async () => {
    const paths: string[] = [];
    const fetchSpy = vi.fn(async (input: RequestInfo | URL) => {
      paths.push(String(input));
      return new Response("{}", {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fetchSpy);

    await saveConfig({ github: { target_repo_url: "x" } });
    await getPrompts();
    await savePrompts({ editor: { system: "y" } });
    await getContent();
    await getImageQueue();

    expect(paths).toContain("/v1/admin/config");
    expect(paths).toContain("/v1/admin/prompts");
    expect(paths).toContain("/v1/admin/content");
    expect(paths).toContain("/v1/admin/images");
  });
});

describe("phase 4 parity client", () => {
  it("unpublishArticle DELETEs the content path", async () => {
    mockFetchResponse(200, { status: "ok", detail: "Unpublished x", updated: 1 });
    await unpublishArticle("2026-01-01-x");
    const fetchMock = vi.mocked(fetch);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/v1/admin/content/2026-01-01-x");
    expect(init.method).toBe("DELETE");
  });

  it("bulkResetContent POSTs refinery ids", async () => {
    mockFetchResponse(200, {
      succeeded: ["a"],
      failed: [{ refinery_id: "b", error: "nope" }],
      summary: "1 succeeded, 1 failed",
    });
    const result = await bulkResetContent(["a", "b"]);
    const fetchMock = vi.mocked(fetch);
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({
      refinery_ids: ["a", "b"],
    });
    expect(result.succeeded).toEqual(["a"]);
  });

  it("updateImageBrief PUTs fields", async () => {
    mockFetchResponse(200, { brief: { topic: "x" }, asset_path: "" });
    await updateImageBrief("slug-1", { topic: "x" });
    const fetchMock = vi.mocked(fetch);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/v1/admin/images/slug-1");
    expect(init.method).toBe("PUT");
  });

  it("uploadImageBriefAsset uses FormData without JSON content-type", async () => {
    setToken("admin-key");
    mockFetchResponse(200, { brief: { status: "editorial_image_ready" }, asset_path: "a.png" });
    const file = new File([new Uint8Array([1, 2, 3])], "hero.png", { type: "image/png" });
    const result = await uploadImageBriefAsset("slug-1", file, { draft_alt_text: "alt" });
    const fetchMock = vi.mocked(fetch);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/v1/admin/images/slug-1/upload");
    expect(init.method).toBe("POST");
    expect(init.body).toBeInstanceOf(FormData);
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer admin-key");
    expect(result.brief.status).toBe("editorial_image_ready");
  });

  it("deleteSource DELETEs the source path", async () => {
    mockFetchResponse(200, { status: "ok", detail: "deleted", updated: 1 });
    await deleteSource("source-1");
    const fetchMock = vi.mocked(fetch);
    expect(String(fetchMock.mock.calls[0][0])).toBe("/v1/admin/sources/source-1");
  });
});

describe("phase 4 addendum: source editor client", () => {
  it("upsertSource POSTs the source payload", async () => {
    setToken("admin-key");
    mockFetchResponse(200, { status: "ok", detail: "Source new_source created", updated: 1 });

    const result = await upsertSource({
      source_id: "new_source",
      name: "New Source",
      url: "https://example.com/feed",
      credibility_score: 0.7,
      category: "science",
      update_frequency: "daily",
      group: "CUSTOM",
    });

    expect(result.status).toBe("ok");
    const fetchMock = vi.mocked(fetch);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/v1/admin/sources");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toMatchObject({
      source_id: "new_source",
      name: "New Source",
      credibility_score: 0.7,
    });
  });
});
