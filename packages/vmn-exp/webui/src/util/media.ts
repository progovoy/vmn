/** Pure helpers of the run page's Media section: histogram geometry and the
 *  table page URL. */
import { appTag } from "../http";
import type { ExperimentDetail, HistogramItem } from "../types";

export interface Bar {
  x: number;
  y: number;
  w: number;
  h: number;
  count: number;
  lo: number;
  hi: number;
}

/** `[lowest edge, highest edge]` over every step. */
export function histogramRange(items: HistogramItem[]): [number, number] {
  let lo = Infinity;
  let hi = -Infinity;
  for (const item of items) {
    lo = Math.min(lo, item.bins[0]);
    hi = Math.max(hi, item.bins[item.bins.length - 1]);
  }
  return [lo, hi];
}

/** One rect per bin in a `width` x `height` box: x by the bin's edges (over
 *  `range`, default the item's own), height relative to its tallest bin. */
export function histogramBars(
  item: HistogramItem, width: number, height: number, range?: [number, number],
): Bar[] {
  const [lo, hi] = range ?? histogramRange([item]);
  const scale = hi > lo ? width / (hi - lo) : 0;
  const tallest = Math.max(0, ...item.counts);
  return item.counts.map((count, i) => {
    const h = tallest > 0 ? (count * height) / tallest : 0;
    const x = (item.bins[i] - lo) * scale;
    return {
      x, y: height - h, w: (item.bins[i + 1] - lo) * scale - x, h, count,
      lo: item.bins[i], hi: item.bins[i + 1],
    };
  });
}

type MediaFields = Pick<ExperimentDetail, "media" | "tables" | "histograms" | "histograms_total">;

export function hasMedia(detail: MediaFields): boolean {
  return [detail.media, detail.tables, detail.histograms, detail.histograms_total].some(
    (index) => index != null && Object.keys(index).length > 0,
  );
}

export interface TableQuery {
  offset: number;
  limit: number;
  sort?: string;
  order?: "asc" | "desc";
}

const encodePath = (path: string) => path.split("/").map(encodeURIComponent).join("/");

const experimentPath = (ws: string, app: string, verstr: string) =>
  `/workspaces/${ws}/apps/${appTag(app)}/experiments/${encodeURIComponent(verstr)}`;

/** The API path (below `/api/v1`) of one page of a logged table. */
export function tablePageUrl(
  ws: string, app: string, verstr: string, path: string, q: TableQuery,
): string {
  const qs = new URLSearchParams({ offset: String(q.offset), limit: String(q.limit) });
  if (q.sort) {
    qs.set("sort", q.sort);
    qs.set("order", q.order ?? "asc");
  }
  return `${experimentPath(ws, app, verstr)}/table/${encodePath(path)}?${qs}`;
}

/** The API path (below `/api/v1`) of one histogram key's served steps. */
export function histogramUrl(ws: string, app: string, verstr: string, name: string): string {
  return `${experimentPath(ws, app, verstr)}/histograms/${encodePath(name)}`;
}
