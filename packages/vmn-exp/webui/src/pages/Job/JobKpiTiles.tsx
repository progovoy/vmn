/** The Overview's KPI tiles (plan 23 §3.2): stat tiles, not charts — each
 *  a label over one number; the best metric links to its run. */
import { Link } from "react-router-dom";
import type { JobPageSummary } from "../../apiJob";
import { runHref } from "../../util";
import { jobKpis, type KpiTile } from "./jobData";

function TileBody({ tile }: { tile: KpiTile }) {
  return (
    <>
      <span className="job-kpi-label">
        {tile.tone && <span className={`job-kpi-dot tone-${tile.tone}`} aria-hidden="true" />}
        {tile.label}
      </span>
      <span className="job-kpi-value">{tile.value}</span>
      {tile.sub && <span className="job-kpi-sub">{tile.sub}</span>}
    </>
  );
}

export default function JobKpiTiles({ summary, runBase }: { summary: JobPageSummary; runBase: string }) {
  return (
    <ul className="job-kpis" aria-label="Outer run KPIs">
      {jobKpis(summary).map((tile) => (
        <li key={tile.label} className="job-kpi">
          {tile.href
            ? <Link className="job-kpi-link" to={runHref(runBase, tile.href)}><TileBody tile={tile} /></Link>
            : <TileBody tile={tile} />}
        </li>
      ))}
    </ul>
  );
}
