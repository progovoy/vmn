/** A job's `412 matching runs` chip in a Jobs view search (plan 23 W11):
 *  opens the job's Runs tab with the same filter. Single runs get none. */
import { Link } from "react-router-dom";
import type { ExperimentRow } from "../types";
import { plural } from "../util";
import { matchingRunsHref, type SearchFilter } from "../util/searchScope";

export default function MatchingRunsChip({ r, runBase, search }: {
  r: ExperimentRow; runBase: string; search?: SearchFilter | null;
}) {
  if (!search || !r.job || !r.matched) return null;
  return (
    <Link className="matching-runs-chip" to={matchingRunsHref(runBase, r.verstr, search)}>
      {plural(r.matched, "matching run")}
    </Link>
  );
}
