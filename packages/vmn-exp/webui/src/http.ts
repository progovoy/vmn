/** The one place requests learn the ui token and turn failures into errors.
 *  Kept apart from api.ts so modules whose tests mock `../api` still share it. */
import { reportUnauthorized } from "./auth/authState";
import { currentSignal } from "./requestScope";
import { TOKEN_KEY } from "./shell/contracts";

export const BASE = "/api/v1";

/** App names appear in URLs in vmn's dashed tag form (`/` -> `-`). */
export const appTag = (name: string) => name.replaceAll("/", "-");

/** What every request throws: the message plus the HTTP status. */
export type HttpError = Error & { status?: number; body?: unknown };

export function authHeaders(extra?: Record<string, string>): Record<string, string> {
  const token = sessionStorage.getItem(TOKEN_KEY);
  const headers: Record<string, string> = { ...extra };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  return headers;
}

export function get<T>(path: string, signal = currentSignal()): Promise<T> {
  return send<T>("GET", path, undefined, signal);
}

export function post<T>(path: string, body: unknown, signal = currentSignal()): Promise<T> {
  return send<T>("POST", path, body, signal);
}

export function del(path: string): Promise<void> {
  return send<void>("DELETE", path);
}

export function patch<T>(path: string, body: unknown): Promise<T> {
  return send<T>("PATCH", path, body);
}

/** Every request. A 401 is reported to the auth state (the shell then asks
 *  for a sign-in) and thrown like any error: nothing is retried behind the
 *  caller's back, so a mutation is never sent twice. */
async function send<T>(method: string, path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const json = method === "POST" || method === "PATCH";
  const sentToken = sessionStorage.getItem(TOKEN_KEY);
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: authHeaders(json ? { "Content-Type": "application/json" } : undefined),
    ...(json ? { body: JSON.stringify(body) } : {}),
    signal,
  });
  // A 401 for a token the user has since replaced (a poll sent before the
  // sign-in) says nothing about the new one: reporting it would swap the
  // page the session banner just kept for the sign-in page.
  const stale = sessionStorage.getItem(TOKEN_KEY) !== sentToken;
  return parse<T>(res, stale ? null : method);
}

async function parse<T>(res: Response, reportAs: string | null): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    if (res.status === 401 && reportAs) reportUnauthorized({ hints: body.auth ?? null, method: reportAs });
    // The status rides along: a 400 is the caller's input (a bad experiment
    // query, say) and is shown next to the input, not as a page error.
    throw Object.assign(new Error(body.detail || `HTTP ${res.status}`), {
      status: res.status,
      body,
    });
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}
