import { useEffect, useRef, useState } from "react";
import { BASE } from "../http";
import { TOKEN_KEY } from "../shell/contracts";
import { useTabVisible } from "./useTabVisible";

/** One `change` event of `GET .../apps/{app}/events` (plan 23 S5). */
export type LiveChange = {
  generation: string;
  changed: { rows: number; jobs?: string[] };
};

/** Errors in a row (without an open in between) before polling takes over. */
const MAX_ERRORS = 3;

export type LiveScope = {
  /** The stream is open: the page needs no polling of its own. */
  connected: boolean;
  /** When the last change arrived (ms since the epoch), null before one. */
  lastChangeAt: number | null;
};

/** Push instead of polling: follows the app's (or one run subtree's)
 *  changes over Server-Sent Events and calls *onChange* on each one — the
 *  page revalidates what it shows (with its ETags). Once a dropped stream is
 *  back, *onChange* runs once (changes may have been missed meanwhile).
 *
 *  Closed while disabled (paused) or the tab is hidden. Never connected —
 *  the caller keeps polling — where EventSource is missing, for a bearer-
 *  token session (EventSource sends no Authorization header), once the
 *  server refuses the stream (no background refresher, too many streams) or
 *  after repeated errors; a new app or scope tries again. */
export function useLiveScope({ ws, app, scope, enabled, onChange }: {
  ws: string;
  /** The app in URL tag form. */
  app: string;
  /** A run's verstr (its subtree), or "top"; the whole app when absent. */
  scope?: string;
  enabled: boolean;
  onChange: (change?: LiveChange) => void;
}): LiveScope {
  const saved = useRef(onChange);
  saved.current = onChange;
  const fire = useSerialized(saved);
  const visible = useTabVisible();
  const [connected, setConnected] = useState(false);
  const [lastChangeAt, setLastChangeAt] = useState<number | null>(null);
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  const opened = useRef<string | null>(null);

  const query = scope ? `?scope=${encodeURIComponent(scope)}` : "";
  const url = `${BASE}/workspaces/${ws}/apps/${app}/events${query}`;
  const supported = typeof EventSource !== "undefined" && !sessionStorage.getItem(TOKEN_KEY);
  const active = supported && enabled && visible && failedUrl !== url;

  useEffect(() => {
    if (!active) return;
    const source = new EventSource(url);
    let errors = 0;
    source.onopen = () => {
      errors = 0;
      setConnected(true);
      if (opened.current === url) fire();
      opened.current = url;
    };
    source.onerror = () => {
      setConnected(false);
      errors += 1;
      if (source.readyState === EventSource.CLOSED || errors >= MAX_ERRORS) {
        source.close();
        setFailedUrl(url);
      }
    };
    source.addEventListener("change", (e) => {
      setLastChangeAt(Date.now());
      fire(parseChange((e as MessageEvent).data));
    });
    return () => {
      source.close();
      setConnected(false);
    };
  }, [active, url, fire]);

  return { connected: active && connected, lastChangeAt };
}

const isThenable = (v: unknown): v is PromiseLike<unknown> =>
  typeof (v as PromiseLike<unknown> | null)?.then === "function";

type OnChange = (change?: LiveChange) => unknown;

/** *callback.current*, never overlapping itself: while the promise it
 *  returned is pending, further calls fold into one trailing call (with the
 *  latest change). */
function useSerialized(callback: { current: OnChange }) {
  const state = useRef({ busy: false, pending: null as { change?: LiveChange } | null });
  const fire = useRef((change?: LiveChange) => {
    const s = state.current;
    if (s.busy) {
      s.pending = { change };
      return;
    }
    let result: unknown;
    try {
      result = callback.current(change);
    } catch {
      result = undefined; // the next change is the retry
    }
    if (!isThenable(result)) return;
    s.busy = true;
    const done = () => {
      s.busy = false;
      const next = s.pending;
      s.pending = null;
      if (next) fire.current(next.change);
    };
    result.then(done, done);
  });
  return fire.current;
}

function parseChange(data: unknown): LiveChange | undefined {
  try {
    return JSON.parse(String(data)) as LiveChange;
  } catch {
    return undefined;
  }
}
