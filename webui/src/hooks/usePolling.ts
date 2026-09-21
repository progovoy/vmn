import { useEffect, useRef, useState } from "react";

/** Interval polling that pauses while the tab is backgrounded — a hidden tab
 *  nobody is looking at has no reason to keep asking the server. */
export function usePolling(callback: () => void, intervalMs: number, enabled: boolean) {
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
    const id = setInterval(() => savedCallback.current(), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs, enabled, visible]);
}
