/** A lazy route's Suspense fallback: announced at once, drawn only after
 *  150 ms, so a fast load never flashes a skeleton. */
import { useEffect, useState } from "react";
import { Skeleton } from "../ui";
import "./NotFound.css";

const DRAW_AFTER_MS = 150;

export default function PageFallback({ label }: { label: string }) {
  const [drawn, setDrawn] = useState(false);
  useEffect(() => {
    const t = window.setTimeout(() => setDrawn(true), DRAW_AFTER_MS);
    return () => window.clearTimeout(t);
  }, []);
  return (
    <div className="route-fallback" aria-busy="true">
      <span role="status" className="fallback-status">Loading {label}…</span>
      {drawn && (
        <>
          <div className="fallback-head" aria-hidden="true" />
          <Skeleton />
        </>
      )}
    </div>
  );
}
