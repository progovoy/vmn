import type { PendingRow } from "../util/sweepTree";

/** What stands in for an open outer's inner runs not shown (grid and cards). */
export const PENDING_TEXT: Record<PendingRow["state"], (p: PendingRow) => string> = {
  loading: () => "Loading inner runs…",
  error: () => "Could not load the inner runs",
  more: (p) => `${p.count} more inner runs · `,
};
