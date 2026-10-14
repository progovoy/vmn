/** Which explicit picks the selected query groups also match (util/
 *  selectionOverlap.ts), asked of the server once per (group, picks): the
 *  list endpoint under the group's scope and filter, narrowed to the picks.
 *  While a new answer is on its way, the earlier ones of the same group
 *  still count for the picks they covered, so the tray's number doesn't jump. */
import { useQueries, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import type { RunPick } from "../util/runSelection";
import type { QueryGroup } from "../util/selectionGroups";
import { overlapCandidates, overlapQuery } from "../util/selectionOverlap";

interface OverlapData { candidates: string[]; overlap: string[] }
type Dropped = ReadonlySet<string>;

const groupId = (g: QueryGroup) => JSON.stringify([g.scope, g.q, g.status]);

function overlapOptions(ws: string, app: string, g: QueryGroup, candidates: string[]) {
  return {
    queryKey: ["selection-overlap", ws, app, groupId(g), [...candidates].sort()],
    queryFn: async (): Promise<OverlapData> => {
      const page = await api.experimentsPaged(ws, app, {
        scope: g.scope, query: overlapQuery(g.q, candidates), status: g.status || undefined, limit: candidates.length,
      });
      return { candidates, overlap: page.rows.map((r) => r.verstr) };
    },
    staleTime: 30_000,
  };
}

/** What the answers so far (the current one and earlier ones of the same
 *  group, cached) say of *candidates*: which the group matches, and whether
 *  some are not asked about yet. */
function knownOverlap(candidates: string[], answers: readonly (OverlapData | undefined)[]) {
  const now = new Set(candidates);
  const asked = new Set(answers.flatMap((a) => a?.candidates ?? []));
  const overlap = new Set(answers.flatMap((a) => a?.overlap ?? []).filter((v) => now.has(v)));
  return { overlap: [...overlap], unknown: candidates.some((v) => !asked.has(v)) };
}

export function useSelectionOverlap(ws: string, app: string, picks: readonly RunPick[], groups: readonly QueryGroup[]) {
  const client = useQueryClient();
  const asks = groups.map((g) => ({ g, candidates: overlapCandidates(g, picks) })).filter((a) => a.candidates.length);
  const results = useQueries({ queries: asks.map(({ g, candidates }) => overlapOptions(ws, app, g, candidates)) });
  const cachedOf = (g: QueryGroup) =>
    client.getQueriesData<OverlapData>({ queryKey: ["selection-overlap", ws, app, groupId(g)] }).map(([, d]) => d);
  const known = asks.map(({ g, candidates }, i) => {
    const current = results[i]?.data;
    return knownOverlap(candidates, current ? [current] : cachedOf(g));
  });
  const dropped: Dropped = new Set(known.flatMap((k) => k.overlap));
  const approximate = known.some((k) => k.unknown);

  /** The overlap once every group answered (a failed answer drops nothing more). */
  const resolved = (): Promise<Dropped> => {
    if (!approximate) return Promise.resolve(dropped);
    return Promise.all(asks.map(({ g, candidates }) =>
      client.ensureQueryData(overlapOptions(ws, app, g, candidates)).then((d) => d.overlap, () => [])))
      .then((lists) => new Set([...dropped, ...lists.flat()]));
  };
  /** *fn* with the overlap: at once when it is known, else once it is. */
  const withResolved = (fn: (d: Dropped) => void) => {
    if (approximate) void resolved().then(fn);
    else fn(dropped);
  };
  return { dropped, approximate, resolved, withResolved };
}
