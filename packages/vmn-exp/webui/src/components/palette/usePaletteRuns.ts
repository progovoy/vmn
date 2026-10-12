/** What ⌘K lists besides its own pages: runs, models and reports. */
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api";
import { apiModels, type ModelRow } from "../../apiModels";
import { apiReports, type ReportRow } from "../../apiReports";
import { useDebounce } from "../../hooks/useDebounce";
import type { ExperimentRow } from "../../types";
import { runSearchQuery } from "../../util/searchQuery";

const RUNS = 20;
/** The newest runs stay fresh this long, so reopening ⌘K costs no request. */
const RECENT_STALE_MS = 30_000;
const CATALOG_STALE_MS = 60_000;

/** The runs the palette offers: the newest until something is typed, then a
 *  server search over every run — never just a filter of the newest 20. */
export function usePaletteRuns(ws: string | undefined, app: string | undefined, needle: string) {
  const client = useQueryClient();
  const scoped = Boolean(ws && app);
  const recent = useQuery<ExperimentRow[]>({
    queryKey: ["recent-runs", ws, app],
    queryFn: () => api.recentExperiments(ws!, app!, RUNS),
    enabled: scoped,
    staleTime: RECENT_STALE_MS,
  }, client);
  const typed = useDebounce(needle, 250);
  const search = useQuery<ExperimentRow[]>({
    queryKey: ["run-search", ws, app, typed],
    queryFn: () =>
      api.experimentsPaged(ws!, app!, { query: runSearchQuery(typed), limit: RUNS }).then((p) => p.rows),
    enabled: scoped && Boolean(typed),
    staleTime: RECENT_STALE_MS,
    placeholderData: keepPreviousData,
  }, client);
  if (needle && typed && search.data) return { runs: search.data, searched: true };
  return { runs: recent.data ?? [], searched: false };
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
