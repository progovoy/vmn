/** The runs a palette command names: every `@N` and prefix in one debounced
 *  request (archived included, as `vmn-exp show -v @N` resolves them too),
 *  `latest` through the run detail. */
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, appTag } from "../../api";
import { apiShell } from "../../apiShell";
import { useDebounce } from "../../hooks/useDebounce";
import type { RunLabel } from "../../shell/contracts";
import type { ExperimentRow } from "../../types";
import { quoteLiteral } from "../../util/searchQuery";

export type RefState =
  | { state: "ok"; run: RunLabel } | { state: "none" } | { state: "several" } | { state: "pending" };
export interface RefResolution { pending: boolean; results: Record<string, RefState> }

const IDX = /^@(\d+)$/;
const STALE_MS = 30_000;

/** `idx in (…)` for the indexes, OR-ed with a substring match per prefix. */
export function refQuery(refs: string[]): string {
  const idx = refs.flatMap((r) => IDX.exec(r)?.[1] ?? []);
  const parts = idx.length ? [`idx in (${idx.join(", ")})`] : [];
  for (const ref of refs) {
    const lit = !IDX.test(ref) && ref !== "latest" ? quoteLiteral(ref) : null;
    if (lit) parts.push(`verstr ~ ${lit}`);
  }
  return parts.join(" or ");
}

const label = (r: ExperimentRow): RunLabel => ({ verstr: r.verstr, idx: r.idx ?? null, name: r.name ?? null });

/** `~` is a substring match: keep the rows the prefix starts; an exact verstr wins. */
function matchRef(ref: string, rows: ExperimentRow[]): RefState {
  const idx = IDX.exec(ref)?.[1];
  const hits = idx
    ? rows.filter((r) => r.idx === Number(idx))
    : rows.find((r) => r.verstr === ref) ? rows.filter((r) => r.verstr === ref)
    : rows.filter((r) => r.verstr.startsWith(ref));
  if (hits.length === 1) return { state: "ok", run: label(hits[0]) };
  return { state: hits.length ? "several" : "none" };
}

export function useRefResolution(ws: string | undefined, app: string | undefined, refs: string[]): RefResolution {
  const key = refs.join(" ");
  const debounced = useDebounce(key, 150);
  const list = useMemo(() => (debounced ? debounced.split(" ") : []), [debounced]);
  const query = refQuery(list);
  const scoped = Boolean(ws && app);
  const wantsLatest = list.includes("latest");

  const rows = useQuery<ExperimentRow[]>({
    queryKey: ["palette-refs", ws, app, query],
    queryFn: () => api.experimentsPaged(ws!, app!, { query, limit: list.length + 20, archived: true })
      .then((p) => p.rows),
    enabled: scoped && Boolean(query),
    staleTime: STALE_MS,
  });
  const latest = useQuery<RunLabel | null>({
    queryKey: ["palette-latest", ws, app],
    queryFn: () => apiShell.resolveRef(ws!, appTag(app!), "latest"),
    enabled: scoped && wantsLatest,
    staleTime: STALE_MS,
  });

  const pending = scoped && refs.length > 0 && (
    debounced !== key || (Boolean(query) && rows.isPending) || (wantsLatest && latest.isPending)
  );
  const results: Record<string, RefState> = {};
  for (const ref of refs) {
    if (pending) results[ref] = { state: "pending" };
    else if (ref === "latest") results[ref] = latest.data ? { state: "ok", run: latest.data } : { state: "none" };
    else results[ref] = matchRef(ref, rows.data ?? []);
  }
  return { pending, results };
}
