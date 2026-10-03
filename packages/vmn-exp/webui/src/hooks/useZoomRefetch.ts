import { useCallback, useEffect, useRef, useState } from "react";
import type { SeriesPoint } from "../types";
import type { StepRange, Zoom } from "../util/zoomSeries";

/** A drag-zoom settles this long before its range is fetched. */
export const ZOOM_DEBOUNCE_MS = 250;

/** Fetches *metric*'s points of a step range at full resolution. */
export type FetchRange = (metric: string, lo: number, hi: number) => Promise<SeriesPoint[]>;

/** Full-fidelity zoom for one chart: *onXRange* reports the visible step
 *  range (null when reset to the whole series); once it settles, that range
 *  is fetched. Until the answer lands *zoom* stays as it was, so the coarse
 *  series keeps drawing; answers a newer zoom superseded are dropped. */
export function useZoomRefetch(metric: string, fetchRange: FetchRange | undefined) {
  const [zoom, setZoom] = useState<Zoom | null>(null);
  const [loading, setLoading] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout>>();
  const latest = useRef<string | null>(null);
  const fetchRef = useRef(fetchRange);
  fetchRef.current = fetchRange;

  useEffect(() => () => clearTimeout(timer.current), []);

  const onXRange = useCallback((range: StepRange | null) => {
    clearTimeout(timer.current);
    const id = range && `${range[0]}:${range[1]}`;
    if (id === latest.current) return;
    latest.current = id;
    if (!range || !fetchRef.current) {
      setZoom(null);
      setLoading(false);
      return;
    }
    timer.current = setTimeout(() => {
      setLoading(true);
      fetchRef.current!(metric, range[0], range[1]).then(
        (points) => {
          if (latest.current !== id) return;
          setZoom({ range, points });
          setLoading(false);
        },
        () => { if (latest.current === id) setLoading(false); },
      );
    }, ZOOM_DEBOUNCE_MS);
  }, [metric]);

  return { zoom, loading, onXRange };
}
