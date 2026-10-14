/** The Jobs view search's result line (plan 23 W11, §3.5):
 *  `3 jobs · 412 runs match · show all 412 runs`, the last part All runs
 *  with the filter kept. */
import { Link } from "react-router-dom";
import { allRunsHref, matchLine, type SearchFilter } from "../../util/searchScope";

export default function JobsMatchLine({ matches, appBase, search }: {
  matches?: { jobs: number; runs: number }; appBase: string; search: SearchFilter | null;
}) {
  if (!matches || !search) return null;
  const { found, all } = matchLine(matches.jobs, matches.runs);
  return (
    <p className="page-sub jobs-match-line" role="status">
      <span>{found}</span>
      {all && <> · <Link to={allRunsHref(appBase, search)}>{all}</Link></>}
    </p>
  );
}
