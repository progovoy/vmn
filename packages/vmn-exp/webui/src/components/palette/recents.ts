/** The destinations ⌘K offers under Recent: the newest first, one per path. */
import { RECENT_KEY } from "../../shell/contracts";

export interface RecentEntry { label: string; to: string; kind: string }

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

export function pushRecent(entry: RecentEntry): void {
  const next = [entry, ...readRecents().filter((r) => r.to !== entry.to)].slice(0, MAX);
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify(next));
  } catch {
    // A full or blocked storage only costs the Recent section.
  }
}
