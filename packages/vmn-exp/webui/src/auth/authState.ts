/** Whether the server wants a sign-in, and how. A module store rather than a
 *  React context, so http.ts can report a 401 from outside any component. */
import { useSyncExternalStore } from "react";
import type { QueryClient } from "@tanstack/react-query";
import type { AuthHints } from "../shell/contracts";
import type { Meta } from "../types";

export interface AuthState {
  required: boolean;
  hints: AuthHints | null;
  /** The HTTP method of the request that got the 401: a GET replaces the
   *  page with the sign-in page, a mutation only adds a banner. */
  method: string | null;
}

const SIGNED_IN: AuthState = { required: false, hints: null, method: null };

let state = SIGNED_IN;
const listeners = new Set<() => void>();

function setState(next: AuthState) {
  state = next;
  listeners.forEach((l) => l());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useAuthState(): AuthState {
  return useSyncExternalStore(subscribe, () => state);
}

/** The first report wins until cleared: a later GET 401 must not turn the
 *  banner over a half-filled form into a page swap, nor the reverse. */
export function reportUnauthorized({ hints, method }: { hints: AuthHints | null; method: string }) {
  if (state.required) return;
  setState({ required: true, hints, method });
}

export function clearUnauthorized() {
  if (state.required) setState(SIGNED_IN);
}

function hintsOf(meta?: Meta): AuthHints | null {
  const auth = meta?.auth;
  return auth ? { token: auth.token, oidc: auth.oidc, login_url: auth.login_url } : null;
}

export async function signOut(client: QueryClient, meta?: Meta): Promise<void> {
  sessionStorage.removeItem("vmn_token");
  if (meta?.auth?.oidc) {
    // /auth lives outside the API base, so this is a raw fetch, not post().
    await fetch("/auth/logout", { method: "POST", credentials: "same-origin" }).catch(() => {});
  }
  client.clear();
  setState({ required: true, hints: hintsOf(meta), method: "GET" });
}
