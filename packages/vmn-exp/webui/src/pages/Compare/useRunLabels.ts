/** Labels for the selection chips (`@N name`, verstr in the title) without
 *  loading each run: a run detail another tab already fetched, a cached
 *  leaderboard row, else one bounded lookup of the whole selection. */
import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api";
import { findCachedRow, runQuery } from "../../queries";
import { runText } from "../../shell/crumbs";
import { verstrInQuery } from "../../util/searchQuery";
import { isOuterRun, outerRunCount } from "../../util/outerRun";
import type { ExperimentDetail, ExperimentRow } from "../../types";

export interface RunChipLabel {
  ref: string;
  text: string;
  /** Loading the run (on the table tab) failed: an unknown ref. */
  missing: boolean;
  /** An outer run: its verstr, name, subtree size and whether it logs metrics itself. */
  outer: OuterInfo | null;
}

export interface OuterInfo {
  verstr: string;
  name: string;
  count: number | null;
  logsMetrics: boolean;
}

/** Metrics the run logged, not its numeric params' fold. */
const logsMetrics = (metrics: Record<string, unknown> = {}, params: Record<string, unknown> = {}) =>
  Object.keys(metrics).some((k) => !(k in params));

function outerOf(ref: string, d: ExperimentDetail | undefined, row: ExperimentRow | undefined): OuterInfo | null {
  const fields = d?.status ?? row;
  if (!fields || !isOuterRun(fields)) return null;
  const verstr = d?.metadata.verstr ?? row?.verstr ?? ref;
  return {
    verstr, name: d?.name || row?.name || verstr,
    count: (row && outerRunCount(row)) ?? (d?.status ? outerRunCount(d.status) : null),
    logsMetrics: logsMetrics(d?.metrics ?? row?.metrics, d?.params ?? row?.params),
  };
}

export function useRunLabels(ws: string, app: string, refs: string[]): RunChipLabel[] {
  const client = useQueryClient();
  // enabled: false only watches the cache, so the curves tab loads no detail.
  const details = useQueries({
    queries: refs.map((v) => ({ ...runQuery(ws, app, v), enabled: false })),
  }, client);
  const lookup = useQuery({
    queryKey: ["compare-labels", ws, app, refs],
    queryFn: () => api.experimentsPaged(ws, app, {
      query: verstrInQuery(refs), limit: refs.length, archived: true,
    }).then((page) => page.rows),
    enabled: refs.length > 0,
    staleTime: 60_000,
    retry: false,
  }, client);

  return refs.map((ref, i) => {
    const d = details[i]?.data;
    const row = findCachedRow(client, ws, app, ref) ?? lookup.data?.find((r) => r.verstr === ref);
    const idx = d?.idx ?? row?.idx ?? null;
    const name = (d?.name ?? row?.name ?? null) || null;
    return {
      ref,
      text: idx == null ? ref : runText({ verstr: ref, idx, name }),
      missing: !!details[i]?.error,
      outer: outerOf(ref, d, row),
    };
  });
}
