import { useEffect, useRef, useState } from "react";
import { TOKEN_KEY } from "../shell/contracts";
import { subscribeLive, type LiveChange } from "./liveHub";
import { isThenable } from "./usePolling";
import { useTabVisible } from "./useTabVisible";

export type { LiveChange } from "./liveHub";

export type LiveScope = {
  /** The stream is open: the page needs no polling of its own. */
  connected: boolean;
};

/** Push instead of polling: follows the app's (or one run subtree's)
 *  changes over Server-Sent Events and calls *onChange* on each one — the
 *  page revalidates what it shows (with its ETags). Once a dropped stream is
 *  back, *onChange* runs once (changes may have been missed meanwhile).
 *
 *  Every page of the tab shares one stream (liveHub). A bearer-token
 *  session reads it over fetch (EventSource sends no Authorization header,
 *  `FetchEventSource`). Closed while disabled (paused) or the tab is
 *  hidden. Never connected — the caller keeps polling — where EventSource
 *  is missing, once the server refuses the stream (no background
 *  refresher, too many streams) or after repeated errors; a new app or
 *  scope tries again. */
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
  const opened = useRef<string | null>(null);

  const token = Boolean(sessionStorage.getItem(TOKEN_KEY));
  const supported = token ? typeof fetch !== "undefined" : typeof EventSource !== "undefined";
  const active = supported && enabled && visible;

  useEffect(() => {
    if (!active) return;
    return subscribeLive({
      ws, app, scope,
      onChange: fire,
      onConnected: setConnected,
      onOpen: (url) => {
        if (opened.current === url) fire();
        opened.current = url;
      },
    });
  }, [active, ws, app, scope, fire]);

  return { connected: active && connected };
}

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
