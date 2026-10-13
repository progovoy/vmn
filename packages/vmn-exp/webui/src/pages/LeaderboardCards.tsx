/** The leaderboard below 640px (plan 20 C8): one card per run — name and
 *  status, the primary metric large, branch · when — instead of a grid
 *  the phone would scroll sideways. */
import { memo, type MouseEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import type { ExperimentRow } from "../types";
import { fmtVal, relTime, runHref } from "../util";
import { isPending, type PendingRow, type TableItem } from "../util/sweepTree";
import { PENDING_TEXT } from "./pendingText";
import StatusPill from "../components/StatusPill";
import { HeaderCheckbox, type HeaderCheckProps } from "./LeaderboardHeadParts";
import { FoldToggle, type RowLayout } from "./LeaderboardRow";
import type { SortState } from "./LeaderboardHead";
import "./leaderboardCards.css";

/** The metric a card shows large: the one sorted by, else the primary
 *  (the bar column), else the first shown. */
export function cardMetric(layout: RowLayout, sort: string | null): string | null {
  const shown = layout.metricCols;
  if (sort && shown.includes(sort)) return sort;
  return shown.find((m) => layout.colMeta[m]?.isBar) ?? shown[0] ?? null;
}

const headStatus = (r: ExperimentRow) =>
  (r.kind === "outer" && r.tree_status ? r.tree_status : r.status) as ExperimentRow["status"];

function MetricLine({ r, metric, layout }: { r: ExperimentRow; metric: string; layout: RowLayout }) {
  const col = layout.colMeta[metric];
  const v = r.metrics[metric];
  const best = layout.showBest && typeof v === "number" && v === col?.best;
  return (
    <div className="lb-mcard-metric">
      <span className={`lb-mcard-value metric${best ? " best" : ""}${v == null ? " missing" : ""}`}>{fmtVal(v)}</span>
      <span className="lb-mcard-label">
        {metric}{col?.goal && <span className="goal"> {col.goal === "min" ? "↓" : "↑"}</span>}
      </span>
    </div>
  );
}

const MCard = memo(function MCard({
  r, layout, metric, selected, flash, collapsed, onToggle, onFold, onPrefetch,
}: {
  r: ExperimentRow; layout: RowLayout; metric: string | null; selected: boolean; flash: boolean;
  collapsed: boolean | null;
  onToggle: (verstr: string, range: boolean) => void;
  onFold: (r: ExperimentRow) => void;
  onPrefetch: (verstr: string) => void;
}) {
  const navigate = useNavigate();
  const href = runHref(layout.runBase, r.verstr);
  const status = headStatus(r);
  const onClick = (e: MouseEvent) => {
    if ((e.target as HTMLElement).closest("a, input, button")) return;
    navigate(href);
  };
  const inner = r.children?.length ? `${r.children.length} inner` : "";
  return (
    <li
      className={`lb-mcard${selected ? " checked" : ""}${flash ? " flash" : ""}${r.archived ? " archived" : ""}`}
      style={{ marginLeft: (r.depth ?? 0) * 14 }}
      onClick={onClick}
    >
      <input
        type="checkbox" checked={selected} aria-label={`Select ${r.verstr}`}
        onChange={() => {}} onClick={(e) => onToggle(r.verstr, e.shiftKey)}
      />
      <div className="lb-mcard-body">
        <div className="lb-mcard-head">
          {collapsed !== null && <FoldToggle r={r} collapsed={collapsed} onFold={onFold} />}
          <Link
            className={`lb-mcard-name run-link${r.name ? " run-name" : " mono"}`} to={href} title={r.verstr}
            onFocus={() => onPrefetch(r.verstr)}
          >
            {r.name || r.verstr}
          </Link>
          {status && (
            <StatusPill
              status={status} exitCode={r.exit_code} durationSec={r.duration_sec}
              staleSec={r.stale_sec} errorSummary={r.error_summary}
            />
          )}
        </div>
        {(r.name || inner) && (
          <div className="lb-mcard-sub mono">{[r.name ? r.verstr : "", inner].filter(Boolean).join(" · ")}</div>
        )}
        {metric && <MetricLine r={r} metric={metric} layout={layout} />}
        {r.status === "failed" && r.error_summary && (
          <div className="lb-mcard-error" title={r.error_summary}>{r.error_summary}</div>
        )}
        <div className="lb-mcard-foot" title={r.timestamp ?? ""}>
          @{r.idx} · {r.branch ?? "—"} · {relTime(r.timestamp)}
        </div>
      </div>
    </li>
  );
});

function PendingCard({ item, runBase }: { item: PendingRow; runBase: string }) {
  return (
    <li
      className={`lb-mcard-pending ${item.state}`} style={{ marginLeft: item.depth * 14 }}
      role={item.state === "error" ? "alert" : undefined}
    >
      {PENDING_TEXT[item.state](item)}
      {item.state === "more" && <Link to={runHref(runBase, item.parent)}>open the outer run</Link>}
    </li>
  );
}

export default function LeaderboardCards({
  rows, layout, sort, selected, flash, onToggle, headerCheck, onPrefetch, collapsedOf, onFold,
}: {
  rows: TableItem[] | undefined;
  layout: RowLayout;
  sort: SortState;
  selected: ReadonlySet<string>;
  flash: string | null;
  onToggle: (verstr: string, range: boolean) => void;
  headerCheck?: HeaderCheckProps;
  onPrefetch: (verstr: string) => void;
  collapsedOf: (r: ExperimentRow) => boolean | null;
  onFold: (r: ExperimentRow) => void;
}) {
  const metric = cardMetric(layout, sort.sort);
  return (
    <div className="lb-mcards-wrap">
      <div className="lb-mcards-head">
        {headerCheck && <HeaderCheckbox {...headerCheck} />}
        {metric && <span className="lb-mcards-metric">{metric}</span>}
      </div>
      {rows === undefined ? (
        <p className="lb-mcards-loading" role="status">loading runs…</p>
      ) : (
        <ul className="lb-mcards" role="list" aria-label="experiments">
          {rows.map((r) => (isPending(r) ? (
            <PendingCard key={r.key} item={r} runBase={layout.runBase} />
          ) : (
            <MCard
              key={r.verstr} r={r} layout={layout} metric={metric}
              selected={selected.has(r.verstr)} flash={flash === r.verstr}
              collapsed={collapsedOf(r)} onToggle={onToggle} onFold={onFold} onPrefetch={onPrefetch}
            />
          )))}
        </ul>
      )}
    </div>
  );
}
