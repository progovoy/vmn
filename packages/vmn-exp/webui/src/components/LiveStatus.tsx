import { useEffect, useState } from "react";
import { humanizeSeconds } from "../util";
import "./LiveStatus.css";

/** The page's freshness: "● live · updated 3s ago" with Pause while a visible
 *  run is running (Resume once paused), a plain Refresh otherwise. The
 *  polite live region carries the state only, so the ticking age is never
 *  read out. */
export default function LiveStatus({
  running, paused, updatedAt, onPause, onResume, onRefresh,
}: {
  running: boolean;
  paused: boolean;
  /** When the shown data last arrived (ms since the epoch). */
  updatedAt: number;
  onPause: () => void;
  onResume: () => void;
  onRefresh: () => void;
}) {
  const state = !running ? "Nothing running, live updates off"
    : paused ? "Live updates paused" : "Live updates on";
  return (
    <span className="live-status">
      <span className="sr-only" aria-live="polite">{state}</span>
      {running ? (
        <>
          <LiveText paused={paused} updatedAt={updatedAt} />
          {paused
            ? <button onClick={onResume}>Resume</button>
            : <button onClick={onPause}>Pause</button>}
        </>
      ) : (
        <button onClick={onRefresh}>Refresh</button>
      )}
    </span>
  );
}

/** "● live · updated 3s ago" (or "paused · …"), ticking each second: what
 *  LiveStatus shows while a run is running, and the phone board's head. */
export function LiveText({ paused, updatedAt }: { paused: boolean; updatedAt: number }) {
  const now = useNow(true);
  const age = `updated ${humanizeSeconds(Math.max(0, (now - updatedAt) / 1000))} ago`;
  return (
    <span className={`live-status-text${paused ? " paused" : ""}`}>
      {!paused && <span className="live-dot" aria-hidden />}
      {paused ? "paused" : "live"} · {age}
    </span>
  );
}

/** The current time, re-read every second while *ticking*. */
function useNow(ticking: boolean): number {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    if (!ticking) return;
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [ticking]);
  return now;
}
