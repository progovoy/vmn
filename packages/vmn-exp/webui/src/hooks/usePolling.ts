import { useEffect, useRef, useState } from "react";

const isThenable = (v: unknown): v is PromiseLike<unknown> =>
  typeof (v as PromiseLike<unknown> | null)?.then === "function";

/** Polling that pauses while the tab is backgrounded — a hidden tab nobody is
 *  looking at has no reason to keep asking the server.
 *
 *  Polls never overlap: when *callback* returns a promise, the next poll is
 *  scheduled *intervalMs* after it settles, so a request slower than the
 *  interval can't pile up behind itself. */
export function usePolling(
  callback: () => unknown, intervalMs: number, enabled: boolean
) {
  const savedCallback = useRef(callback);
  savedCallback.current = callback;
  const [visible, setVisible] = useState(
    () => document.visibilityState !== "hidden"
  );

  useEffect(() => {
    const onChange = () => setVisible(document.visibilityState !== "hidden");
    document.addEventListener("visibilitychange", onChange);
    return () => document.removeEventListener("visibilitychange", onChange);
  }, []);

  useEffect(() => {
    if (!enabled || !visible) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const schedule = () => {
      if (!cancelled) timer = setTimeout(tick, intervalMs);
    };
    function tick() {
      let result: unknown;
      try {
        result = savedCallback.current();
      } catch {
        result = undefined; // the next poll is the retry
      }
      if (isThenable(result)) result.then(schedule, schedule);
      else schedule();
    }

    schedule();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [intervalMs, enabled, visible]);
}
