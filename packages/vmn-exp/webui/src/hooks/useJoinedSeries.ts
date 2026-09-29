import { useEffect, useState } from "react";
import type { XMap } from "../util/xMetric";

/** What *fetchJoined* answers for *xMap*, re-fetched whenever the map or
 *  *token* (the plain series, so a poll refreshes the joins) changes; null
 *  until it arrives or when nothing needs a join. A failed fetch keeps the
 *  charts on their plain axis. *fetchJoined* must be stable. */
export function useJoinedSeries<T>(
  xMap: XMap, fetchJoined: ((xMap: XMap) => Promise<T>) | undefined, token: unknown,
): T | null {
  const key = JSON.stringify(xMap);
  const [state, setState] = useState<{ key: string; data: T } | null>(null);
  useEffect(() => {
    if (!fetchJoined || key === "{}") return;
    let live = true;
    fetchJoined(JSON.parse(key) as XMap).then(
      (data) => { if (live) setState({ key, data }); },
      () => {},
    );
    return () => { live = false; };
  }, [key, fetchJoined, token]);
  return state && state.key === key ? state.data : null;
}
