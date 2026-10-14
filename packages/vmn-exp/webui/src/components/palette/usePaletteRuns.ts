/** What ⌘K lists besides its own pages: runs, models and reports. */
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api";
import { searchRuns, type RunSearchHit } from "../../apiRunSearch";
import { apiModels, type ModelRow } from "../../apiModels";
import { apiReports, type ReportRow } from "../../apiReports";
import { useDebounce } from "../../hooks/useDebounce";
import type { ExperimentRow } from "../../types";

const RUNS = 20;
/** The newest runs stay fresh this long, so reopening ⌘K costs no request. */
const RECENT_STALE_MS = 30_000;
const CATALOG_STALE_MS = 60_000;
const TYPING_MS = 150;

/** A run the palette lists; a search hit also names its job. */
export type PaletteRun = ExperimentRow & { root_name?: string | null };

const hitRow = (h: RunSearchHit) =>
  ({ verstr: h.verstr, idx: h.idx, name: h.name, status: h.status, root_name: h.root ? h.root_name : null,
     timestamp: null, note: null }) as unknown as PaletteRun;

/** The runs the palette offers: the newest until something is typed, then
 *  the server's run search over every run (plan 23 S8: `@N`, name, verstr
 *  prefix, tags, notes) — never just a filter of the newest 20. */
export function usePaletteRuns(ws: string | undefined, app: string | undefined, needle: string) {
  const client = useQueryClient();
  const scoped = Boolean(ws && app);
  const recent = useQuery<ExperimentRow[]>({
    queryKey: ["recent-runs", ws, app],
    queryFn: () => api.recentExperiments(ws!, app!, RUNS),
    enabled: scoped,
    staleTime: RECENT_STALE_MS,
  }, client);
  const typed = useDebounce(needle, TYPING_MS);
  const search = useQuery<PaletteRun[]>({
    queryKey: ["run-search", ws, app, typed],
    queryFn: () => searchRuns(ws!, app!, typed, RUNS).then((hits) => hits.map(hitRow)),
    enabled: scoped && Boolean(typed),
    staleTime: RECENT_STALE_MS,
    placeholderData: keepPreviousData,
  }, client);
  if (needle && typed && search.data) return { runs: search.data, searched: true };
  return { runs: (recent.data ?? []) as PaletteRun[], searched: false };
}

/** The workspace's models and reports, fetched once a search is 2+ chars long. */
export function usePaletteCatalog(ws: string | undefined, enabled: boolean) {
  const on = Boolean(ws) && enabled;
  const models = useQuery<ModelRow[]>({
    queryKey: ["palette-models", ws],
    queryFn: () => apiModels.listModels(ws!).then((r) => r.models),
    enabled: on,
    staleTime: CATALOG_STALE_MS,
  });
  const reports = useQuery<ReportRow[]>({
    queryKey: ["palette-reports", ws],
    queryFn: () => apiReports.listReports(ws!).then((r) => r.reports),
    enabled: on,
    staleTime: CATALOG_STALE_MS,
  });
  return { models: models.data ?? [], reports: reports.data ?? [] };
}
