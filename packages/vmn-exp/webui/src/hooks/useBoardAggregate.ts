/** The grouped board's aggregate (plan 22 G10, F3): the URL's `agg=`, else
 *  what the server resolved it to (the app's conf default included). */
import { useCallback } from "react";
import type { Aggregate } from "../util/groupBy";
import type { useBoardGrouping } from "./useBoardGrouping";
import type { useLeaderboardView } from "./useLeaderboardView";

type View = Pick<ReturnType<typeof useLeaderboardView>, "aggParam" | "setAggregate">;

/** *server*: the payload's `aggregate`, and the one it answered without
 *  `agg=` (the app's default, unknown until such an answer came). */
export function useBoardAggregate(
  grouping: ReturnType<typeof useBoardGrouping>,
  view: View,
  server: { aggregate?: Aggregate; defaultAggregate?: Aggregate },
) {
  const { aggParam, setAggregate: write } = view;
  const { aggregate: answered, defaultAggregate } = server;
  // Without agg=, a placeholder answer may still be another aggregate's.
  const aggregate: Aggregate = aggParam ?? defaultAggregate ?? answered ?? "mean";
  const setAggregate = useCallback((a: Aggregate) => write(a, defaultAggregate), [write, defaultAggregate]);
  return { ...grouping, aggregate, setAggregate };
}

export type BoardGrouping = ReturnType<typeof useBoardAggregate>;
