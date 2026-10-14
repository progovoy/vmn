/** Explicit picks that a selected query group also matches: the board never
 *  loaded them (else the group would have absorbed them), so only the
 *  server knows. The tray asks it per group and counts those picks once. */
import type { RunPick } from "./runSelection";
import type { QueryGroup } from "./selectionGroups";

/** The picks a group may also match: those of its outer run, and those
 *  whose outer run is unknown. */
export const overlapCandidates = (g: QueryGroup, picks: readonly RunPick[]) =>
  picks.filter((p) => p.job === undefined || p.job === g.job || p.job === g.scope).map((p) => p.verstr);

/** `verstr in ("a", "b")`. */
export const verstrInQuery = (verstrs: readonly string[]) =>
  `verstr in (${verstrs.map((v) => JSON.stringify(v)).join(", ")})`;

/** The group's query narrowed to *verstrs*. */
export const overlapQuery = (q: string, verstrs: readonly string[]) =>
  q ? `(${q}) and ${verstrInQuery(verstrs)}` : verstrInQuery(verstrs);
