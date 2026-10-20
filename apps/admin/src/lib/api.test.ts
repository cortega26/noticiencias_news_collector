/**
 * Vitest suite for the admin API client. Uses a stubbed global fetch so no
 * backend is required.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  AUTH_BYPASS,
  ApiError,
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
  getQualityRecent,
  getSourceHealth,
  getToken,
  listArticles,
  listSources,
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
  startPublishBatch,
  getPublishStatus,
  toggleSource,
  unpublishArticle,
  upsertSource,
  updateAuditStatus,
  updateImageBrief,
  uploadImageBriefAsset,
} from './api';
import type { AdminArticleListEnvelope } from './types';

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

vi.stubGlobal('localStorage', new MemoryStorage());

const envelope: AdminArticleListEnvelope = {
  data: [
    {
      id: 1,
      title: 'CRISPR gene therapy milestone',
      summary: 'Breakthrough',
      url: 'https://example.com/1',
      source: { id: 'nature', name: 'Nature' },
      category: 'science',
      topics: ['science'],
      published_at: null,
      collected_at: '2026-08-13T10:00:00Z',
      final_score: 0.92,
      score_components: { source_credibility: 0.95 },
      why_ranked: ['Fuente altamente confiable'],
      processing_status: 'pending',
      error_message: null,
      published_url: null,
      refinery_id: 'refinery-1',
      publishable: true,
      export_score: 0.92,
    },
  ],
  pagination: { next_cursor: null, has_more: false, page_size: 20, returned: 1 },
  filters: { status: 'pending', source: [] },
  meta: { generated_at: '2026-08-13T10:00:00Z' },
};

function mockFetchResponse(status: number, body: unknown): void {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify(body), {
        status,
        headers: { 'Content-Type': 'application/json' },
      })
    )
  );
}

function mockFetchReject(): void {
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
}

function mockFetchRawResponse(status: number, body: string, contentType?: string): void {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(
      new Response(body, {
        status,
        headers: contentType ? { 'Content-Type': contentType } : {},
      })
    )
  );
}

/** Capture the `Request` objects the typed client sends (openapi-fetch uses Request). */
function mockFetchCapture(body: unknown): Request[] {
  const requests: Request[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      requests.push(input as Request);
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    })
  );
  return requests;
}

function requestAt(index = 0): Request {
  const [request] = vi.mocked(fetch).mock.calls[index] as [Request];
  return request;
}

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('token helpers', () => {
  it('persists and clears the token in localStorage', () => {
    expect(getToken()).toBeNull();
    setToken('admin-key');
    expect(getToken()).toBe('admin-key');
    expect(localStorage.getItem('refinery_admin_token')).toBe('admin-key');
    clearToken();
    expect(getToken()).toBeNull();
  });

  it('does not bypass auth outside the dev server (MODE=test)', () => {
    expect(AUTH_BYPASS).toBe(false);
    expect(getToken()).toBeNull();
  });
});

describe('listArticles', () => {
  it('sends the Bearer token and status filter', async () => {
    setToken('admin-key');
    mockFetchResponse(200, envelope);

    const result = await listArticles('pending');

    expect(result.data).toHaveLength(1);
    expect(result.data[0].title).toBe('CRISPR gene therapy milestone');
    const request = requestAt();
    const url = new URL(request.url);
    expect(url.pathname).toBe('/v1/admin/articles');
    expect(url.search).toBe('?status=pending&page_size=20');
    expect(request.method).toBe('GET');
    expect(request.headers.get('Authorization')).toBe('Bearer admin-key');
  });

  it('appends the cursor when provided, preserving page_size and order', async () => {
    setToken('admin-key');
    mockFetchResponse(200, envelope);
    // Server-issued cursors are urlsafe base64; these are the characters a
    // real cursor can carry.
    const cursor = 'eyJpZCI6MX0=';

    await listArticles('pending', cursor, 50);

    const url = new URL(requestAt().url);
    expect(url.search).toBe(`?status=pending&page_size=50&cursor=${encodeURIComponent(cursor)}`);
  });

  it('omits an empty cursor like the previous client', async () => {
    setToken('admin-key');
    mockFetchResponse(200, envelope);

    await listArticles('pending', '');

    expect(new URL(requestAt().url).search).toBe('?status=pending&page_size=20');
  });

  it("passes the virtual 'publishable' filter through as a status", async () => {
    setToken('admin-key');
    mockFetchResponse(200, envelope);

    await listArticles('publishable');

    expect(new URL(requestAt().url).search).toBe('?status=publishable&page_size=20');
  });

  it('throws AuthError on 401', async () => {
    mockFetchResponse(401, { detail: 'Missing Authorization header' });
    await expect(listArticles('pending')).rejects.toBeInstanceOf(AuthError);
  });

  it('throws AuthError on 403', async () => {
    mockFetchResponse(403, { detail: 'Invalid admin API key' });
    await expect(listArticles('pending')).rejects.toBeInstanceOf(AuthError);
  });

  it('throws NotFoundError on 404', async () => {
    mockFetchResponse(404, { detail: 'Article not found' });
    await expect(listArticles('pending')).rejects.toBeInstanceOf(NotFoundError);
  });

  it('throws ValidationError on 422', async () => {
    mockFetchResponse(422, { detail: "Invalid status 'bogus'" });
    const err = await listArticles('pending').catch((e) => e);
    expect(err).toBeInstanceOf(ValidationError);
    expect((err as ValidationError).message).toContain('bogus');
  });

  it('throws NetworkError when fetch rejects', async () => {
    mockFetchReject();
    await expect(listArticles('pending')).rejects.toBeInstanceOf(NetworkError);
  });

  it.each([502, 503, 504])(
    'maps gateway status %i to a NetworkError that names the fix',
    async (status) => {
      mockFetchResponse(status, '');
      const err = await listArticles('pending').catch((e) => e);
      expect(err).toBeInstanceOf(NetworkError);
      expect((err as NetworkError).message).toContain('serving API');
      expect((err as NetworkError).message).toContain('make admin');
    }
  );

  it('parses a JSON error body on other 5xx instead of a bare HTTP error', async () => {
    mockFetchResponse(500, { detail: 'boom' });
    const err = await listArticles('pending').catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).not.toBeInstanceOf(NetworkError);
    expect((err as ApiError).status).toBe(500);
    expect((err as ApiError).detail).toBe('boom');
  });
});

describe('structured API errors', () => {
  const capabilityBody = {
    detail:
      'Published content is unavailable in this deployment. This route requires the local admin stack: a git binary and a frontend checkout (missing here: a frontend checkout).',
    error_code: 'published_content_unavailable',
  };

  it('carries status, errorCode and detail from the 503 capability body', async () => {
    mockFetchResponse(503, capabilityBody);

    const err = await getContent().catch((e) => e);

    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(503);
    expect((err as ApiError).errorCode).toBe('published_content_unavailable');
    expect((err as ApiError).detail).toContain('requires the local admin stack');
    // Not a transport failure: the operator must not be told to debug the network.
    expect(err).not.toBeInstanceOf(NetworkError);
  });

  it('parses a structured body whose content-type is not JSON', async () => {
    mockFetchRawResponse(503, JSON.stringify(capabilityBody));

    const err = await getContent().catch((e) => e);

    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).errorCode).toBe('published_content_unavailable');
  });

  it('keeps NetworkError for a 503 with a non-JSON body', async () => {
    mockFetchRawResponse(503, '<html><body>Bad Gateway</body></html>', 'text/html');

    const err = await getContent().catch((e) => e);

    expect(err).toBeInstanceOf(NetworkError);
    expect(err).not.toBeInstanceOf(ApiError);
    expect((err as Error).message).toContain('HTTP 503');
  });

  it('does not crash on an empty 503 body', async () => {
    mockFetchRawResponse(503, '');

    const err = await getContent().catch((e) => e);

    expect(err).toBeInstanceOf(NetworkError);
  });
});

describe('getArticle (openapi-fetch pilot)', () => {
  it('requests the typed path and sends the Bearer token', async () => {
    setToken('admin-key');
    mockFetchResponse(200, { id: 1, title: 'x' });

    const result = await getArticle(1);

    expect(result.id).toBe(1);
    const [request] = vi.mocked(fetch).mock.calls[0] as [Request];
    expect(new URL(request.url).pathname).toBe('/v1/admin/articles/1');
    expect(request.headers.get('Authorization')).toBe('Bearer admin-key');
  });

  it('reads the token at request time, not when the client is created', async () => {
    const fetchSpy = vi.fn().mockImplementation(
      async () =>
        new Response(JSON.stringify({ id: 1 }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
    );
    vi.stubGlobal('fetch', fetchSpy);

    setToken('first-key');
    await getArticle(1);
    setToken('second-key');
    await getArticle(1);

    const requests = fetchSpy.mock.calls.map(([request]) => request as Request);
    expect(requests[0].headers.get('Authorization')).toBe('Bearer first-key');
    expect(requests[1].headers.get('Authorization')).toBe('Bearer second-key');
  });

  it('throws AuthError on 401', async () => {
    mockFetchResponse(401, { detail: 'Missing Authorization header' });

    const err = await getArticle(1).catch((e) => e);

    expect(err).toBeInstanceOf(AuthError);
    expect((err as Error).message).toBe('Authentication required');
  });

  it('throws AuthError on 403', async () => {
    mockFetchResponse(403, { detail: 'Invalid admin API key' });

    const err = await getArticle(1).catch((e) => e);

    expect(err).toBeInstanceOf(AuthError);
    expect((err as Error).message).toBe('Authentication required');
  });

  it('throws NotFoundError on 404', async () => {
    mockFetchResponse(404, { detail: 'Article not found' });

    const err = await getArticle(1).catch((e) => e);

    expect(err).toBeInstanceOf(NotFoundError);
    expect((err as Error).message).toBe('Not found');
  });

  it('throws ValidationError carrying the 422 detail', async () => {
    mockFetchResponse(422, { detail: "Invalid article id 'x'" });

    const err = await getArticle(1).catch((e) => e);

    expect(err).toBeInstanceOf(ValidationError);
    expect((err as Error).message).toBe("Invalid article id 'x'");
  });

  it('keeps the default ValidationError message for an empty 422', async () => {
    mockFetchRawResponse(422, '');

    const err = await getArticle(1).catch((e) => e);

    expect(err).toBeInstanceOf(ValidationError);
    expect((err as Error).message).toBe('Invalid request');
  });

  it('throws ConflictError carrying the parsed 409 body', async () => {
    mockFetchResponse(409, { run_id: '5', detail: 'already running' });

    const err = await getArticle(1).catch((e) => e);

    expect(err).toBeInstanceOf(ConflictError);
    expect((err as ConflictError).body).toEqual({ run_id: '5', detail: 'already running' });
    expect((err as Error).message).toBe('A conflicting operation is already in progress');
  });

  it('throws NetworkError when fetch rejects', async () => {
    mockFetchReject();

    const err = await getArticle(1).catch((e) => e);

    expect(err).toBeInstanceOf(NetworkError);
    expect((err as Error).message).toContain('make admin');
  });

  it.each([502, 503, 504])(
    'maps an unstructured gateway %i to NetworkError naming the fix',
    async (status) => {
      mockFetchRawResponse(status, '<html><body>Bad Gateway</body></html>', 'text/html');

      const err = await getArticle(1).catch((e) => e);

      expect(err).toBeInstanceOf(NetworkError);
      expect((err as Error).message).toContain(`HTTP ${status}`);
      expect((err as Error).message).toContain('make admin');
    }
  );

  it('carries the structured 503 capability body as ApiError', async () => {
    mockFetchResponse(503, {
      detail:
        'Published content is unavailable in this deployment. This route requires the local admin stack.',
      error_code: 'published_content_unavailable',
    });

    const err = await getArticle(1).catch((e) => e);

    expect(err).toBeInstanceOf(ApiError);
    expect(err).not.toBeInstanceOf(NetworkError);
    expect((err as ApiError).status).toBe(503);
    expect((err as ApiError).errorCode).toBe('published_content_unavailable');
    expect((err as ApiError).detail).toContain('requires the local admin stack');
  });

  it('parses a structured 503 body whose content-type is not JSON', async () => {
    mockFetchRawResponse(
      503,
      JSON.stringify({ detail: 'capability missing', error_code: 'published_content_unavailable' })
    );

    const err = await getArticle(1).catch((e) => e);

    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).errorCode).toBe('published_content_unavailable');
  });

  it('throws ApiError for a structured 500', async () => {
    mockFetchResponse(500, { detail: 'boom' });

    const err = await getArticle(1).catch((e) => e);

    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(500);
    expect((err as ApiError).detail).toBe('boom');
  });

  it('throws the generic HTTP error for an unstructured 500', async () => {
    mockFetchRawResponse(500, 'oops', 'text/plain');

    const err = await getArticle(1).catch((e) => e);

    expect(err).not.toBeInstanceOf(ApiError);
    expect(err).not.toBeInstanceOf(NetworkError);
    expect((err as Error).message).toBe('HTTP 500');
  });
});

describe('mutation endpoints (openapi-fetch)', () => {
  it('rejectArticle POSTs the reason', async () => {
    setToken('admin-key');
    mockFetchResponse(200, {
      status: 'ok',
      detail: 'Rejected publication attempt refinery-1',
      updated: 1,
    });

    const result = await rejectArticle(1, 'duplicate');

    expect(result.status).toBe('ok');
    const request = requestAt();
    expect(new URL(request.url).pathname).toBe('/v1/admin/articles/1/reject');
    expect(request.method).toBe('POST');
    expect(request.headers.get('Authorization')).toBe('Bearer admin-key');
    expect(request.headers.get('Content-Type')).toBe('application/json');
    expect(await request.text()).toBe('{"reason":"duplicate"}');
  });

  it('updateAuditStatus POSTs audit_status', async () => {
    setToken('admin-key');
    mockFetchResponse(200, {
      status: 'ok',
      detail: "Audit status 'failed' recorded",
      updated: 1,
    });

    const result = await updateAuditStatus(7, 'failed', 'low signal');

    expect(result.status).toBe('ok');
    const request = requestAt();
    expect(new URL(request.url).pathname).toBe('/v1/admin/articles/7/audit-status');
    expect(request.method).toBe('POST');
    expect(request.headers.get('Authorization')).toBe('Bearer admin-key');
    expect(await request.text()).toBe('{"audit_status":"failed","reason":"low signal"}');
  });

  it('startPublishBatch POSTs article_ids', async () => {
    setToken('admin-key');
    mockFetchResponse(202, {
      run_id: '9',
      status: 'queued',
      detail: 'Batch publication started for 2 articles.',
      accepted_ids: [3, 7],
    });

    const result = await startPublishBatch([3, 7]);

    expect(result.run_id).toBe('9');
    expect(result.accepted_ids).toEqual([3, 7]);
    const request = requestAt();
    expect(new URL(request.url).pathname).toBe('/v1/admin/publish/batch');
    expect(request.method).toBe('POST');
    expect(request.headers.get('Authorization')).toBe('Bearer admin-key');
    expect(await request.text()).toBe('{"article_ids":[3,7]}');
  });
});

describe('read endpoints (openapi-fetch)', () => {
  const qualityBody = {
    runs: [],
    aggregate: {
      count: 0,
      succeeded: 0,
      failed: 0,
      with_readability: 0,
      avg_suitability: null,
    },
    meta: { generated_at: '2026-10-19T00:00:00Z' },
  };

  const readCases: Array<{
    name: string;
    call: () => Promise<unknown>;
    path: string;
    search: string;
    body: unknown;
  }> = [
    {
      name: 'getSourceHealth',
      call: () => getSourceHealth(),
      path: '/v1/admin/sources/health',
      search: '',
      body: { sources: [{ source_id: 'nature', consecutive_failures: 0 }] },
    },
    {
      name: 'getAnalytics',
      call: () => getAnalytics(),
      path: '/v1/admin/analytics',
      search: '',
      body: {
        stats: [],
        total_articles: 3,
        source_perf: [],
        avg_score_overall: 0.5,
        dist: {},
        cats: [],
        top_sources: [],
        as_of: '2026-10-19T00:00:00Z',
      },
    },
    {
      name: 'getConfig',
      call: () => getConfig(),
      path: '/v1/admin/config',
      search: '',
      body: {
        environment: 'test',
        debug: false,
        timezone: 'UTC',
        github: {},
        ollama: {},
        scoring: {},
        sources: [],
      },
    },
    {
      name: 'listSources',
      call: () => listSources(),
      path: '/v1/admin/sources',
      search: '',
      body: { sources: [{ source_id: 'nature', name: 'Nature', is_active: true }] },
    },
    {
      name: 'getPrompts',
      call: () => getPrompts(),
      path: '/v1/admin/prompts',
      search: '',
      body: { prompts: { editor: { system: 'x' } } },
    },
    {
      name: 'getContent',
      call: () => getContent(),
      path: '/v1/admin/content',
      search: '',
      body: {
        source_label: 'local',
        freshness_label: 'fresh',
        articles: [{ file_name: 'a.md', title: 'A' }],
      },
    },
    {
      name: 'getImageQueue',
      call: () => getImageQueue(),
      path: '/v1/admin/images',
      search: '',
      body: {
        briefs: [
          {
            slug: 'slug-1',
            article_id: '1',
            status: 'pending',
            reason: 'missing',
            topic: 'science',
            image_origin: 'unknown',
          },
        ],
      },
    },
    {
      name: 'getQualityRecent (default limit)',
      call: () => getQualityRecent(),
      path: '/v1/admin/quality/recent',
      search: '?limit=20',
      body: qualityBody,
    },
    {
      name: 'getQualityRecent (explicit limit)',
      call: () => getQualityRecent(5),
      path: '/v1/admin/quality/recent',
      search: '?limit=5',
      body: qualityBody,
    },
    {
      name: 'getCollectStatus',
      call: () => getCollectStatus('collect/1'),
      path: '/v1/admin/collect/status',
      search: `?run_id=${encodeURIComponent('collect/1')}`,
      body: { run_id: 'collect/1', status: 'running', active: true },
    },
    {
      name: 'getPublishStatus',
      call: () => getPublishStatus('7'),
      path: '/v1/admin/publish/status',
      search: '?run_id=7',
      body: {
        run_id: '7',
        status: 'succeeded',
        active: false,
        pr_url: 'https://github.com/x/y/pull/9',
      },
    },
    {
      name: 'listArticles',
      call: () => listArticles('pending'),
      path: '/v1/admin/articles',
      search: '?status=pending&page_size=20',
      body: envelope,
    },
  ];

  it.each(readCases)(
    '$name sends the documented wire request and parses the body',
    async (testCase) => {
      setToken('admin-key');
      const requests = mockFetchCapture(testCase.body);

      const result = await testCase.call();

      expect(requests).toHaveLength(1);
      const url = new URL(requests[0].url);
      expect(url.pathname).toBe(testCase.path);
      expect(url.search).toBe(testCase.search);
      expect(requests[0].method).toBe('GET');
      expect(requests[0].headers.get('Authorization')).toBe('Bearer admin-key');
      expect(result).toEqual(testCase.body);
    }
  );

  it('omits an empty run_id like the previous client', async () => {
    const requests = mockFetchCapture({});

    await getCollectStatus('');

    expect(new URL(requests[0].url).search).toBe('');
  });
});

describe('phase 3 operational client', () => {
  it('startCollect POSTs dry_run', async () => {
    setToken('admin-key');
    mockFetchResponse(202, {
      run_id: 'collect-1',
      status: 'queued',
      detail: 'Collection started (dry-run)',
    });

    const started = await startCollect(true);

    expect(started.run_id).toBe('collect-1');
    const request = requestAt();
    expect(new URL(request.url).pathname).toBe('/v1/admin/collect');
    expect(request.method).toBe('POST');
    expect(request.headers.get('Authorization')).toBe('Bearer admin-key');
    expect(await request.text()).toBe('{"dry_run":true}');
  });

  it("startCollect throws ConflictError with the existing run's body on 409", async () => {
    mockFetchResponse(409, {
      run_id: 'collect-1',
      status: 'running',
      detail: 'A collection run is already queued or running.',
    });

    const err = await startCollect(false).catch((e) => e);

    expect(err).toBeInstanceOf(ConflictError);
    expect((err as ConflictError).body).toMatchObject({ run_id: 'collect-1' });
  });

  it('getCollectStatus hits the status path with run_id', async () => {
    mockFetchResponse(200, {
      run_id: 'collect-1',
      status: 'running',
      started_at: 'now',
      finished_at: null,
      error: null,
      summary: {},
      active: true,
    });

    await getCollectStatus('collect-1');

    const url = new URL(requestAt().url);
    expect(url.pathname).toBe('/v1/admin/collect/status');
    expect(url.search).toBe('?run_id=collect-1');
  });

  it('startPublish POSTs article_id (url null)', async () => {
    setToken('admin-key');
    mockFetchResponse(202, { run_id: '7', status: 'queued', detail: 'Publication started.' });

    const started = await startPublish({ articleId: 42 });

    expect(started.run_id).toBe('7');
    const request = requestAt();
    expect(new URL(request.url).pathname).toBe('/v1/admin/publish');
    expect(request.method).toBe('POST');
    expect(request.headers.get('Authorization')).toBe('Bearer admin-key');
    expect(await request.text()).toBe('{"article_id":42,"article_url":null}');
  });

  it('startPublish POSTs article_url (id null)', async () => {
    setToken('admin-key');
    mockFetchResponse(202, { run_id: '8', status: 'queued', detail: 'Publication started.' });

    const started = await startPublish({ articleUrl: 'https://example.com/x' });

    expect(started.run_id).toBe('8');
    const request = requestAt();
    expect(request.method).toBe('POST');
    expect(request.headers.get('Authorization')).toBe('Bearer admin-key');
    expect(await request.text()).toBe('{"article_id":null,"article_url":"https://example.com/x"}');
  });

  it('startPublish surfaces a 409 as ConflictError carrying the active run id', async () => {
    mockFetchResponse(409, {
      run_id: '5',
      status: 'running',
      detail: 'A publication run is already queued or running.',
    });

    const err = await startPublish({ articleId: 1 }).catch((e) => e);

    expect(err).toBeInstanceOf(ConflictError);
    expect((err as ConflictError).body).toMatchObject({ run_id: '5' });
  });

  it('startPublish maps a proxy 502 to NetworkError', async () => {
    mockFetchResponse(502, '');
    await expect(startPublish({ articleId: 1 })).rejects.toBeInstanceOf(NetworkError);
  });

  it('getPublishStatus hits the status path with run_id', async () => {
    mockFetchResponse(200, {
      run_id: '7',
      status: 'succeeded',
      started_at: 'now',
      finished_at: 'later',
      error: null,
      summary: { pr_url: 'https://github.com/x/y/pull/9' },
      active: false,
      pr_url: 'https://github.com/x/y/pull/9',
      failure_class: null,
      final_slug: 'gene-therapy',
    });

    const st = await getPublishStatus('7');

    const url = new URL(requestAt().url);
    expect(url.pathname).toBe('/v1/admin/publish/status');
    expect(url.search).toBe('?run_id=7');
    expect(st.pr_url).toBe('https://github.com/x/y/pull/9');
  });

  it('reprocessArticle / toggleSource / resetSourceCircuit POST correctly', async () => {
    setToken('admin-key');

    mockFetchResponse(200, { status: 'ok', detail: 'ok', updated: 1 });
    const reprocessed = await reprocessArticle(5);
    expect(reprocessed.updated).toBe(1);
    let request = requestAt();
    expect(new URL(request.url).pathname).toBe('/v1/admin/articles/5/reprocess');
    expect(request.method).toBe('POST');
    expect(request.headers.get('Authorization')).toBe('Bearer admin-key');
    expect(await request.text()).toBe('{}');

    mockFetchResponse(200, { status: 'ok', detail: 'ok', updated: 1 });
    const toggled = await toggleSource('nature', false);
    expect(toggled.updated).toBe(1);
    request = requestAt();
    expect(new URL(request.url).pathname).toBe('/v1/admin/sources/nature/toggle');
    expect(request.method).toBe('POST');
    expect(request.headers.get('Authorization')).toBe('Bearer admin-key');
    expect(await request.text()).toBe('{"active":false}');

    mockFetchResponse(200, { status: 'ok', detail: 'ok', updated: 1 });
    const reset = await resetSourceCircuit('nature');
    expect(reset.updated).toBe(1);
    request = requestAt();
    expect(new URL(request.url).pathname).toBe('/v1/admin/sources/nature/reset');
    expect(request.method).toBe('POST');
    expect(request.headers.get('Authorization')).toBe('Bearer admin-key');
    expect(await request.text()).toBe('{}');
  });

  it('saveConfig / getPrompts / savePrompts / getContent / getImageQueue hit paths', async () => {
    setToken('admin-key');
    const requests: Request[] = [];
    const fetchSpy = vi.fn(async (input: RequestInfo | URL) => {
      requests.push(input as Request);
      return new Response('{}', {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    });
    vi.stubGlobal('fetch', fetchSpy);

    await saveConfig({ github: { target_repo_url: 'x' }, debug: true });
    await getPrompts();
    await savePrompts({ editor: { system: 'y' } });
    await getContent();
    await getImageQueue();

    expect(requests.map((request) => new URL(request.url).pathname)).toEqual([
      '/v1/admin/config',
      '/v1/admin/prompts',
      '/v1/admin/prompts',
      '/v1/admin/content',
      '/v1/admin/images',
    ]);
    expect(requests[0].method).toBe('POST');
    expect(requests[0].headers.get('Authorization')).toBe('Bearer admin-key');
    expect(await requests[0].text()).toBe('{"github":{"target_repo_url":"x"},"debug":true}');
    expect(requests[2].method).toBe('POST');
    expect(requests[2].headers.get('Authorization')).toBe('Bearer admin-key');
    expect(await requests[2].text()).toBe('{"prompts":{"editor":{"system":"y"}}}');
  });

  it.each([
    ['startCollect', () => startCollect(false)],
    ['startPublish', () => startPublish({ articleId: 1 })],
    ['startPublishBatch', () => startPublishBatch([1])],
  ])('%s maps 422 to ValidationError carrying the detail', async (_name, call) => {
    mockFetchResponse(422, { detail: 'invalid run request' });

    const err = await call().catch((e) => e);

    expect(err).toBeInstanceOf(ValidationError);
    expect((err as Error).message).toBe('invalid run request');
  });

  it('startPublishBatch 409 carries the parsed active-run body', async () => {
    mockFetchResponse(409, {
      run_id: '9',
      status: 'running',
      detail: 'A publication run is already queued or running.',
      accepted_ids: [1],
    });

    const err = await startPublishBatch([1]).catch((e) => e);

    expect(err).toBeInstanceOf(ConflictError);
    expect((err as ConflictError).body).toEqual({
      run_id: '9',
      status: 'running',
      detail: 'A publication run is already queued or running.',
      accepted_ids: [1],
    });
  });

  it('a mutation 401 still maps to AuthError', async () => {
    mockFetchResponse(401, { detail: 'Missing Authorization header' });

    await expect(rejectArticle(1)).rejects.toBeInstanceOf(AuthError);
  });
});

describe('phase 4 parity client', () => {
  it('unpublishArticle DELETEs the content path', async () => {
    setToken('admin-key');
    mockFetchResponse(200, { status: 'ok', detail: 'Unpublished x', updated: 1 });
    const result = await unpublishArticle('2026-01-01-x');
    expect(result.status).toBe('ok');
    const request = requestAt();
    expect(new URL(request.url).pathname).toBe('/v1/admin/content/2026-01-01-x');
    expect(request.method).toBe('DELETE');
    expect(request.headers.get('Authorization')).toBe('Bearer admin-key');
    expect(request.headers.get('Content-Type')).toBeNull();
    expect(await request.text()).toBe('');
  });

  it('bulkResetContent POSTs refinery ids', async () => {
    setToken('admin-key');
    mockFetchResponse(200, {
      succeeded: ['a'],
      failed: [{ refinery_id: 'b', error: 'nope' }],
      summary: '1 succeeded, 1 failed',
    });
    const result = await bulkResetContent(['a', 'b']);
    const request = requestAt();
    expect(new URL(request.url).pathname).toBe('/v1/admin/content/bulk-reset');
    expect(request.method).toBe('POST');
    expect(request.headers.get('Authorization')).toBe('Bearer admin-key');
    expect(await request.text()).toBe('{"refinery_ids":["a","b"]}');
    expect(result.succeeded).toEqual(['a']);
  });

  it('updateImageBrief PUTs fields', async () => {
    setToken('admin-key');
    mockFetchResponse(200, { brief: { topic: 'x' }, asset_path: '' });
    const result = await updateImageBrief('slug-1', {
      topic: 'x',
      image_origin: 'ai_generated',
    });
    const request = requestAt();
    expect(new URL(request.url).pathname).toBe('/v1/admin/images/slug-1');
    expect(request.method).toBe('PUT');
    expect(request.headers.get('Authorization')).toBe('Bearer admin-key');
    expect(await request.text()).toBe('{"topic":"x","image_origin":"ai_generated"}');
    expect(result.asset_path).toBe('');
  });

  it('uploadImageBriefAsset uses FormData without JSON content-type', async () => {
    setToken('admin-key');
    mockFetchResponse(200, { brief: { status: 'editorial_image_ready' }, asset_path: 'a.png' });
    const file = new File([new Uint8Array([1, 2, 3])], 'hero.png', { type: 'image/png' });
    const result = await uploadImageBriefAsset('slug-1', file, {
      draft_alt_text: 'alt',
      image_origin: 'ai_generated',
    });
    const fetchMock = vi.mocked(fetch);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/v1/admin/images/slug-1/upload');
    expect(init.method).toBe('POST');
    expect(init.body).toBeInstanceOf(FormData);
    expect((init.body as FormData).get('image_origin')).toBe('ai_generated');
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer admin-key');
    expect(result.brief.status).toBe('editorial_image_ready');
  });

  it('deleteSource DELETEs the source path', async () => {
    setToken('admin-key');
    mockFetchResponse(200, { status: 'ok', detail: 'deleted', updated: 1 });
    const result = await deleteSource('source-1');
    expect(result.status).toBe('ok');
    const request = requestAt();
    expect(new URL(request.url).pathname).toBe('/v1/admin/sources/source-1');
    expect(request.method).toBe('DELETE');
    expect(request.headers.get('Authorization')).toBe('Bearer admin-key');
    expect(request.headers.get('Content-Type')).toBeNull();
    expect(await request.text()).toBe('');
  });

  it('encodes path parameters like the previous client', async () => {
    mockFetchResponse(200, { status: 'ok', detail: 'deleted', updated: 1 });
    await deleteSource('source/1');
    expect(new URL(requestAt().url).pathname).toBe('/v1/admin/sources/source%2F1');
  });
});

describe('phase 4 addendum: source editor client', () => {
  it('upsertSource POSTs the source payload', async () => {
    setToken('admin-key');
    mockFetchResponse(200, { status: 'ok', detail: 'Source new_source created', updated: 1 });

    const payload = {
      source_id: 'new_source',
      name: 'New Source',
      url: 'https://example.com/feed',
      credibility_score: 0.7,
      category: 'science',
      update_frequency: 'daily',
      group: 'CUSTOM',
    } as const;
    const result = await upsertSource(payload);

    expect(result.status).toBe('ok');
    const request = requestAt();
    expect(new URL(request.url).pathname).toBe('/v1/admin/sources');
    expect(request.method).toBe('POST');
    expect(request.headers.get('Authorization')).toBe('Bearer admin-key');
    expect(await request.text()).toBe(JSON.stringify(payload));
  });
});
