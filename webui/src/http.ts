/** The one place requests learn the ui token and turn failures into errors.
 *  Kept apart from api.ts so modules whose tests mock `../api` still share it. */
import { currentSignal } from "./requestScope";

export const BASE = "/api/v1";

/** What `get` throws: the message plus the HTTP status. */
export type HttpError = Error & { status?: number };

export function authHeaders(extra?: Record<string, string>): Record<string, string> {
  const token = sessionStorage.getItem("vmn_token");
  const headers: Record<string, string> = { ...extra };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  return headers;
}

export async function get<T>(path: string, signal = currentSignal()): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { headers: authHeaders(), signal });
  if (res.status === 401) {
    const entered = window.prompt("vmn ui token:");
    if (entered) {
      sessionStorage.setItem("vmn_token", entered);
      return get<T>(path, signal);
    }
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    // The status rides along: a 400 is the caller's input (a bad experiment
    // query, say) and is shown next to the input, not as a page error.
    throw Object.assign(new Error(body.detail || `HTTP ${res.status}`), {
      status: res.status,
    });
  }
  return res.json();
}
