/**
 * The single place this app talks to the backend.
 *
 * Spec 07: "one typed API client module; no fetch calls scattered in
 * components." Three things have to happen identically on every call, and each
 * one is a bug the day some screen forgets it:
 *
 *   1. the bearer token is attached,
 *   2. a 401 clears the session rather than leaving a dead token that makes
 *      every subsequent call fail with no explanation,
 *   3. a non-2xx becomes a typed error carrying the server's `detail`, because
 *      "409: this approval was already decided" is worth showing and
 *      "Request failed" is not.
 */

import { clearToken, storedToken } from "../auth";

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;

  constructor(status: number, detail: string) {
    super(detail || `Request failed with ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

/** Raised on 401 so the router can bounce to login without every caller checking. */
export class Unauthenticated extends ApiError {
  constructor(detail = "Your session has expired. Sign in again.") {
    super(401, detail);
    this.name = "Unauthenticated";
  }
}

/** Fired once per 401, so the app can end the session rather than each screen
 *  rendering an error it has no way to recover from. */
export const UNAUTHENTICATED_EVENT = "flowforge:unauthenticated";

type Query = Record<string, string | number | boolean | null | undefined>;

export function withQuery(path: string, query?: Query): string {
  if (!query) return path;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    // Deliberately drops null/undefined/"" rather than sending empty params:
    // an unset filter must not become `?status=` , which FastAPI would try to
    // parse as a value.
    if (value === null || value === undefined || value === "") continue;
    params.set(key, String(value));
  }
  const qs = params.toString();
  return qs ? `${path}?${qs}` : path;
}

async function readDetail(response: Response): Promise<string> {
  try {
    const body = await response.json();
    const detail = (body as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
    // FastAPI validation errors arrive as a list of objects; flatten to the
    // messages rather than showing the caller a JSON blob.
    if (Array.isArray(detail)) {
      return detail
        .map((item) =>
          typeof item === "object" && item && "msg" in item
            ? String((item as { msg: unknown }).msg)
            : String(item),
        )
        .join("; ");
    }
    return detail ? JSON.stringify(detail) : response.statusText;
  } catch {
    return response.statusText;
  }
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  /** Set for multipart uploads, where the browser must pick the boundary. */
  formData?: FormData;
  signal?: AbortSignal;
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const token = storedToken();
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;

  let body: BodyInit | undefined;
  if (options.formData) {
    // No Content-Type header: fetch must set it, including the multipart
    // boundary. Setting it by hand here is the classic silent upload failure.
    body = options.formData;
  } else if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.body);
  }

  const response = await fetch(path, {
    method: options.method ?? "GET",
    headers,
    body,
    signal: options.signal,
  });

  if (response.status === 401) {
    // A stored token that no longer verifies is worse than none at all.
    clearToken();
    // Clearing storage is not the same as ending the session. The live React
    // token is separate state, and the identity query stays fresh for five
    // minutes — so without this the shell, the sidebar and the previous
    // screen's cached data all stayed mounted around an error, with no
    // credential left to recover with. Announce it once, here, so every 401
    // from every screen ends the same way.
    window.dispatchEvent(new Event(UNAUTHENTICATED_EVENT));
    throw new Unauthenticated(await readDetail(response));
  }

  if (!response.ok) {
    throw new ApiError(response.status, await readDetail(response));
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  get: <T>(path: string, query?: Query, signal?: AbortSignal) =>
    request<T>(withQuery(path, query), { signal }),
  post: <T>(path: string, body?: unknown) => request<T>(path, { method: "POST", body }),
  upload: <T>(path: string, formData: FormData) => request<T>(path, { method: "POST", formData }),
};
