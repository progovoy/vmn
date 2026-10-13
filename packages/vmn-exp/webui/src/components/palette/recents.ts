/** The destinations ⌘K offers under Recent: the newest first, one per path. */
import { RECENT_KEY, type RouteId } from "../../shell/contracts";

export interface RecentEntry { label: string; to: string; kind: string }

/** A route's Recent kind: the icon Go to and the search rows use for it
 *  (`app` and `ws` are the stored names of the app and workspace icons). */
const KIND: Partial<Record<RouteId, string>> = {
  run: "run", experiments: "app", "compare-runs": "experiments", "code-diff": "experiments",
  overlay: "experiments", tree: "tree", actions: "actions", apps: "ws", home: "workspace",
  models: "models", model: "models", reports: "reports", report: "reports", "report-edit": "reports",
  tokens: "key",
};
export const recentKindOf = (routeId: RouteId): string => KIND[routeId] ?? "page";

const MAX = 20;

const isEntry = (e: unknown): e is RecentEntry => {
  const r = e as RecentEntry | null;
  return typeof r?.label === "string" && typeof r.to === "string" && typeof r.kind === "string";
};

export function readRecents(): RecentEntry[] {
  try {
    const stored: unknown = JSON.parse(localStorage.getItem(RECENT_KEY) ?? "[]");
    return Array.isArray(stored) ? stored.filter(isEntry) : [];
  } catch {
    return [];
  }
}

function write(entries: RecentEntry[]): void {
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify(entries));
  } catch {
    // A full or blocked storage only costs the Recent section.
  }
}

export function pushRecent(entry: RecentEntry): void {
  write([entry, ...readRecents().filter((r) => r.to !== entry.to)].slice(0, MAX));
}

/** Drop *to*: a destination that turned out missing or broken. */
export function forgetRecent(to: string): void {
  const kept = readRecents();
  const next = kept.filter((r) => r.to !== to);
  if (next.length !== kept.length) write(next);
}
