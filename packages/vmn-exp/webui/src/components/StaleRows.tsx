/** A board's rows while a new filter loads: the old ones dimmed and said
 *  to be updating, and a failed request said over them, not hidden. */
import type { ReactNode } from "react";

export default function StaleRows({ stale, error, children }: {
  stale: boolean; error: string | null; children: ReactNode;
}) {
  return (
    <>
      {error && <div className="error" role="alert">{error}</div>}
      {stale && !error && <p className="board-updating" role="status">updating…</p>}
      <div className="board-rows" aria-busy={stale || undefined}>{children}</div>
    </>
  );
}
