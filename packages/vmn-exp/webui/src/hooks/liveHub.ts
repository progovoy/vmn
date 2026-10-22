/** The tab's one live stream (plan 23 S5). Over plain HTTP a browser keeps
 *  6 connections per host for every tab together, and a stream holds one
 *  for as long as it is open: the pages' subscribers share one connection.
 *  It follows the newest subscriber's app, with the scope all of that app's
 *  subscribers share, else the app's whole stream (a scoped subscriber then
 *  hears the app's changes: one revalidation more, never one less).
 *  Another app's subscribers are told they are not connected (they poll). */
import { authHeaders, BASE } from "../http";
import { TOKEN_KEY } from "../shell/contracts";
import { FetchEventSource } from "../util/fetchEventSource";

/** One `change` event of `GET .../apps/{app}/events`. */
export type LiveChange = {
  generation: string;
  changed: { rows: number; jobs?: string[] };
};

export interface LiveSubscriber {
  ws: string;
  /** The app in URL tag form. */
  app: string;
  /** A run's verstr (its subtree), or "top"; the whole app when absent. */
  scope?: string;
  onChange: (change?: LiveChange) => void;
  /** The stream at *url* is open for this subscriber. */
  onOpen: (url: string) => void;
  onConnected: (connected: boolean) => void;
}

/** Errors in a row (without an open in between) before polling takes over. */
const MAX_ERRORS = 3;

type Source = EventSource | FetchEventSource;

let subs: LiveSubscriber[] = [];
/** The stream, and the subscribers it serves (set by reconcile). */
let current: { url: string; source: Source; open: boolean; members: LiveSubscriber[] } | null = null;
/** Streams refused or failing, until no subscriber is left. */
const failed = new Set<string>();

const urlOf = (ws: string, app: string, scope?: string) =>
  `${BASE}/workspaces/${ws}/apps/${app}/events${scope ? `?scope=${encodeURIComponent(scope)}` : ""}`;

function target(): { url: string; members: LiveSubscriber[] } | null {
  const newest = subs[subs.length - 1];
  if (!newest) return null;
  const members = subs.filter((s) => s.ws === newest.ws && s.app === newest.app);
  const scopes = new Set(members.map((s) => s.scope ?? ""));
  const scope = scopes.size === 1 ? newest.scope : undefined;
  return { url: urlOf(newest.ws, newest.app, scope), members };
}

function close() {
  current?.source.close();
  current = null;
}

function open(url: string) {
  const token = Boolean(sessionStorage.getItem(TOKEN_KEY));
  const source: Source = token ? new FetchEventSource(url, authHeaders()) : new EventSource(url);
  const conn = { url, source, open: false, members: [] as LiveSubscriber[] };
  current = conn;
  const members = () => (current === conn ? conn.members : []);
  let errors = 0;
  source.onopen = () => {
    errors = 0;
    conn.open = true;
    for (const s of members()) {
      s.onConnected(true);
      s.onOpen(url);
    }
  };
  source.onerror = () => {
    conn.open = false;
    for (const s of members()) s.onConnected(false);
    errors += 1;
    if (source.readyState === FetchEventSource.CLOSED || errors >= MAX_ERRORS) {
      failed.add(url);
      source.close();
      if (current === conn) current = null;
    }
  };
  source.addEventListener("change", (e) => {
    const change = parseChange((e as MessageEvent).data);
    for (const s of members()) s.onChange(change);
  });
}

/** Opens, moves or closes the stream for the subscribers there are now. */
function reconcile() {
  const t = target();
  if (!t) {
    close();
    failed.clear();
    return;
  }
  const want = failed.has(t.url) ? null : t.url;
  if (current?.url !== want) {
    close();
    if (want) open(want);
  }
  if (current) current.members = t.members;
  const on = new Set(current?.open ? t.members : []);
  for (const s of subs) s.onConnected(on.has(s));
}

/** Follow *sub*'s changes until the returned function is called. */
export function subscribeLive(sub: LiveSubscriber): () => void {
  subs = [...subs, sub];
  reconcile();
  // Joined a stream already open: as if it had just opened for *sub*.
  if (current?.open && current.members.includes(sub)) sub.onOpen(current.url);
  return () => {
    subs = subs.filter((s) => s !== sub);
    if (current) current.members = current.members.filter((s) => s !== sub);
    sub.onConnected(false);
    // A page unmounting leaves its subscribers one by one: the stream moves
    // once they are all gone, not per subscriber (it closes with the last).
    if (subs.length) queueMicrotask(reconcile);
    else reconcile();
  };
}

function parseChange(data: unknown): LiveChange | undefined {
  try {
    return JSON.parse(String(data)) as LiveChange;
  } catch {
    return undefined;
  }
}
