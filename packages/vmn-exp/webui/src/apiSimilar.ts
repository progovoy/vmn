/** Similar runs (plan 18): `GET .../experiments/{verstr}/similar` — the runs
 *  most like one run — and `GET .../apps/{app}/similar?text=` — the runs whose
 *  intent, name, note, tags or commit subjects match a free text. Both look in
 *  the app, or with `allApps` in every app of the workspace, among the runs a
 *  `query` matches (archived ones with `archived`). */
import { appTag, get } from "./http";

export interface SimilarIntent {
  /** The intent's first 2 KB. */
  text: string;
  keywords: string[];
  truncated: boolean;
}

export interface SimilarItem {
  workspace: string;
  /** The real app name (not the URL tag). */
  app: string;
  verstr: string;
  name: string | null;
  /** 0..1, against the other candidates of this query; never stored. */
  score: number;
  /** Up to three short "why it matched" strings. */
  reasons: string[];
  signals: Record<string, number>;
  /** Runs of one sweep or one code this item stands for. */
  group_size: number;
  /** The group's best run on the goal metric, when the app has a goal. */
  goal: { metric: string; goal: "min" | "max"; value: number | null } | null;
  author: string | null;
  timestamp: string | null;
  status: string;
  note: string | null;
  intent: SimilarIntent | null;
}

export interface SimilarRuns {
  items: SimilarItem[];
  /** More runs matched than `top`. */
  truncated: boolean;
}

export interface SimilarOptions {
  top?: number;
  allApps?: boolean;
  /** Keep only the candidates this query-language query matches (`q`). */
  query?: string;
  /** Let archived runs be candidates. */
  archived?: boolean;
}

function query({ top, allApps, query: q, archived }: SimilarOptions, text?: string): string {
  const p = new URLSearchParams();
  if (text !== undefined) p.set("text", text);
  if (top !== undefined) p.set("top", String(top));
  if (allApps) p.set("all_apps", "1");
  if (q) p.set("q", q);
  if (archived) p.set("archived", "1");
  const qs = p.toString();
  return qs ? `?${qs}` : "";
}

export function runSimilar(
  ws: string, app: string, verstr: string, opts: SimilarOptions = {},
): Promise<SimilarRuns> {
  return get<SimilarRuns>(
    `/workspaces/${ws}/apps/${appTag(app)}/experiments/${encodeURIComponent(verstr)}/similar${query(opts)}`,
  );
}

export function textSimilar(
  ws: string, app: string, text: string, opts: SimilarOptions = {},
): Promise<SimilarRuns> {
  return get<SimilarRuns>(`/workspaces/${ws}/apps/${appTag(app)}/similar${query(opts, text)}`);
}
