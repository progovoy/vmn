/** The runs a palette command names: every `@N` and prefix in one debounced
 *  request (archived included, as `vmn-exp show -v @N` resolves them too),
 *  `latest` as the index's newest run. Both read index rows only. */
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../../api";
import { useDebounce } from "../../hooks/useDebounce";
import { runLabelOf, type RunLabel } from "../../shell/contracts";
import type { ExperimentRow } from "../../types";
import { quoteLiteral } from "../../util/searchQuery";

export type RefState =
  | { state: "ok"; run: RunLabel } | { state: "none" } | { state: "several" } | { state: "pending" };
/** Each ref's state, `pending` until every request it needs has answered. */
export type RefResolution = Record<string, RefState>;

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

const single = (hits: ExperimentRow[]): RefState =>
  hits.length === 1 ? { state: "ok", run: runLabelOf(hits[0]) } : { state: hits.length ? "several" : "none" };

/** `~` is a substring match: keep the rows the prefix starts; an exact verstr wins. */
function matchRef(ref: string, rows: ExperimentRow[]): RefState {
  const idx = IDX.exec(ref)?.[1];
  if (idx) return single(rows.filter((r) => r.idx === Number(idx)));
  const exact = rows.filter((r) => r.verstr === ref);
  return single(exact.length ? exact : rows.filter((r) => r.verstr.startsWith(ref)));
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
  // The server's `latest` is the newest timestamp over every run; its storage
  // order is by timestamp, so the last row of the archived-inclusive window is it.
  const latest = useQuery<ExperimentRow[]>({
    queryKey: ["palette-latest", ws, app],
    queryFn: () => api.experimentsPaged(ws!, app!, { last: 1, limit: 1, archived: true }).then((p) => p.rows),
    enabled: scoped && wantsLatest,
    staleTime: STALE_MS,
  });

  const pending = scoped && refs.length > 0 && (
    debounced !== key || (Boolean(query) && rows.isPending) || (wantsLatest && latest.isPending)
  );
  return Object.fromEntries(refs.map((ref): [string, RefState] => [ref,
    pending ? { state: "pending" }
    : ref === "latest" ? single(latest.data ?? [])
    : matchRef(ref, rows.data ?? []),
  ]));
}
