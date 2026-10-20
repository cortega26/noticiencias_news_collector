/**
 * The admin client's error taxonomy, shared by the hand-written `apiFetch`
 * client and the typed `openapi-fetch` client so the two cannot drift.
 *
 * Every constructor/default message here is part of the UI contract: pages
 * catch these classes by identity and the `AuthGate` relies on `AuthError`.
 */

export class AuthError extends Error {
  constructor(message = 'Authentication required') {
    super(message);
    this.name = 'AuthError';
  }
}

export class NotFoundError extends Error {
  constructor(message = 'Not found') {
    super(message);
    this.name = 'NotFoundError';
  }
}

export class ValidationError extends Error {
  constructor(message = 'Invalid request') {
    super(message);
    this.name = 'ValidationError';
  }
}

/**
 * The serving API could not be reached: `fetch` rejected (DNS/connection
 * refused/CORS) or the dev proxy / a deployment gateway returned 502/503/504
 * because nothing healthy is listening behind it. Almost always "the API is
 * not running" in local dev.
 *
 * A 502/503/504 *with* a structured body is not this class: see
 * {@link ApiError} (e.g. the published-content capability 503, plan 151).
 */
export class NetworkError extends Error {
  constructor(message = 'Cannot reach the serving API — is it running? Try `make admin`.') {
    super(message);
    this.name = 'NetworkError';
  }
}

/** The machine-readable error fields the serving API returns on 4xx/5xx. */
export interface StructuredErrorBody {
  detail: string | undefined;
  errorCode: string | undefined;
}

/**
 * A non-2xx response whose body carried a structured `detail` and/or
 * `error_code` (for example the 503 `published_content_unavailable` from the
 * published-content routes). Unlike {@link NetworkError}, the API answered:
 * the operator needs the reason it gave, not advice to debug the network.
 *
 * The message is the body's `detail` when present so logs and the generic
 * error UI stay informative; `status`, `errorCode` and `detail` are exposed
 * for callers that want to render the reason specifically.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly errorCode: string | undefined;
  readonly detail: string | undefined;

  constructor(status: number, body: StructuredErrorBody) {
    super(body.detail ?? `HTTP ${status}`);
    this.name = 'ApiError';
    this.status = status;
    this.errorCode = body.errorCode;
    this.detail = body.detail;
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
  constructor(body: T, message = 'Conflict') {
    super(message);
    this.name = 'ConflictError';
    this.body = body;
  }
}

/**
 * Read a structured error body without assuming one is present: an empty,
 * non-JSON, or differently-shaped body yields `null` and the caller keeps the
 * previous generic handling. `content-type` is deliberately not trusted — it
 * may be absent or wrong (proxies, test doubles) — so the body is attempted
 * as JSON and only a `detail`/`error_code` object is accepted.
 */
export async function readStructuredError(response: Response): Promise<StructuredErrorBody | null> {
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    return null;
  }
  return asStructuredError(body);
}

function asStructuredError(body: unknown): StructuredErrorBody | null {
  if (body === null || typeof body !== 'object' || Array.isArray(body)) return null;

  const record = body as Record<string, unknown>;
  const detail = typeof record.detail === 'string' && record.detail ? record.detail : undefined;
  const errorCode =
    typeof record.error_code === 'string' && record.error_code ? record.error_code : undefined;
  if (!detail && !errorCode) return null;
  return { detail, errorCode };
}

/**
 * Map an already-parsed non-2xx body (as returned by `openapi-fetch`) to the
 * same class/message `apiFetch` throws. Kept in lockstep with
 * {@link throwHttpError}, which parses the raw `Response` instead.
 */
export function mapOpenApiError(error: unknown, response: Response): Error {
  return errorFromBody(response.status, error);
}

function isGatewayStatus(status: number): boolean {
  return status === 502 || status === 503 || status === 504;
}

function gatewayError(status: number): NetworkError {
  return new NetworkError(
    `Cannot reach the serving API (HTTP ${status}) — is it running? Try \`make admin\`.`
  );
}

function errorFromBody(status: number, body: unknown): Error {
  if (status === 401 || status === 403) return new AuthError();
  if (status === 404) return new NotFoundError();
  if (status === 422) {
    const detail = (body as { detail?: string }).detail;
    return new ValidationError(detail ?? 'Invalid request');
  }
  if (status === 409) {
    return new ConflictError(body, 'A conflicting operation is already in progress');
  }
  // 502/503/504 normally come from the dev proxy or a deployment gateway
  // saying nothing healthy answered on :8000 — but the app itself also
  // answers 503 with a structured `error_code` when a capability is missing
  // (published content, plan 151). Carry that reason instead of blaming the
  // network.
  const structured = asStructuredError(body);
  if (structured) return new ApiError(status, structured);
  if (isGatewayStatus(status)) return gatewayError(status);
  return new Error(`HTTP ${status}`);
}

/**
 * Throw the taxonomy error for a non-2xx `Response`, reading the body exactly
 * as `apiFetch` always has: JSON where a body is expected and `{}` for a 422
 * or 409 whose body is missing/unparseable.
 */
export async function throwHttpError(response: Response): Promise<never> {
  const status = response.status;
  if (status === 401 || status === 403 || status === 404) {
    throw errorFromBody(status, undefined);
  }
  if (status === 422 || status === 409) {
    const body = await response.json().catch(() => ({}));
    throw errorFromBody(status, body);
  }
  const structured = await readStructuredError(response);
  if (structured) throw new ApiError(status, structured);
  if (isGatewayStatus(status)) throw gatewayError(status);
  throw new Error(`HTTP ${status}`);
}
