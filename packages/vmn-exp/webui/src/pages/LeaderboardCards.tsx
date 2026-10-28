/** The leaderboard below 640px (plan 20 C8): one card per run — name and
 *  status, the primary metric large, branch · when — instead of a grid
 *  the phone would scroll sideways; grouped, a section per group (plan 22 G9). */
import { Fragment, memo } from "react";
import { Link } from "react-router-dom";
import type { ExperimentRow } from "../types";
import { fmtVal, relTime, runHref } from "../util";
import { sweepIncompleteLabel } from "../util/sweepProgress";
import RowCheckbox from "../components/RowCheckbox";
import StatusPill from "../components/StatusPill";
import OuterBadge from "../components/OuterBadge";
import { isOuterRun, outerRunCount } from "../util/outerRun";
import { useRowNavigate } from "../hooks/useRowNavigate";
import { HeaderCheckbox, type HeaderCheckProps } from "./LeaderboardHeadParts";
import { headStatus, type RowLayout } from "./LeaderboardRow";
import type { SortState } from "./LeaderboardHead";
import type { GroupActions } from "./LeaderboardTable";
import CardGroup, { CardGroupMore } from "./LeaderboardCardGroup";
import { isGroupItem, memberOf, type BoardItem, type GroupHeaderItem, type GroupMoreItem } from "../util/groupItems";
import "./leaderboardCards.css";

/** The metric a card shows large: the one sorted by, else the primary
 *  (the bar column), else the first shown. */
export function cardMetric(layout: RowLayout, sort: string | null): string | null {
  const shown = layout.metricCols;
  if (sort && shown.includes(sort)) return sort;
  return shown.find((m) => layout.colMeta[m]?.isBar) ?? shown[0] ?? null;
}

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
  r, layout, metric, selected, flash, onToggle,
}: {
  r: ExperimentRow; layout: RowLayout; metric: string | null; selected: boolean; flash: boolean;
  onToggle: (verstr: string, range: boolean) => void;
}) {
  const href = runHref(layout.runBase, r.verstr);
  const status = headStatus(r);
  const onClick = useRowNavigate(href);
  const incomplete = sweepIncompleteLabel(r);
  return (
    <li
      className={`lb-mcard${selected ? " checked" : ""}${flash ? " flash" : ""}${r.archived ? " archived" : ""}`}
      onClick={onClick}
    >
      <RowCheckbox verstr={r.verstr} checked={selected} onToggle={onToggle} />
      <div className="lb-mcard-body">
        <div className="lb-mcard-head">
          <Link className={`lb-mcard-name run-link${r.name ? " run-name" : " mono"}`} to={href} title={r.verstr}>
            {r.name || r.verstr}
          </Link>
          {status && (
            <StatusPill
              status={status} exitCode={r.exit_code} durationSec={r.duration_sec}
              staleSec={r.stale_sec} errorSummary={r.error_summary}
              settled={r.kind === "outer" ? null : r.settled}
            />
          )}
        </div>
        {isOuterRun(r) && <div className="lb-mcard-outer"><OuterBadge count={outerRunCount(r)} to={href} /></div>}
        {r.name && <div className="lb-mcard-sub mono">{r.verstr}</div>}
        {incomplete && <div className="lb-mcard-sweep mono">{incomplete}</div>}
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

/** *items* as sections: each group's header with its runs and `+N more`;
 *  a headless section for the rows of no group (an ungrouped board, the
 *  loose rows, plan 22 F12). */
interface Section { head?: GroupHeaderItem; rows: ExperimentRow[]; more?: GroupMoreItem }

function sectionsOf(items: readonly BoardItem[]): Section[] {
  const owner = memberOf(items);
  const out: Section[] = [];
  items.forEach((it, i) => {
    if (isGroupItem(it) && it.item === "group") return void out.push({ head: it, rows: [] });
    let last = out[out.length - 1];
    if (!last || (last.head && owner[i] !== last.head)) out.push(last = { rows: [] });
    if (isGroupItem(it)) last.more = it;
    else last.rows.push(it);
  });
  return out;
}

export default function LeaderboardCards({
  rows, layout, sort, selected, flash, onToggle, headerCheck, groups, describedBy,
}: {
  rows: BoardItem[] | undefined;
  layout: RowLayout;
  sort: SortState;
  selected: ReadonlySet<string>;
  flash: string | null;
  onToggle: (verstr: string, range: boolean) => void;
  headerCheck?: HeaderCheckProps;
  /** Set while the board is grouped: each group becomes a section (plan 22 G9). */
  groups?: GroupActions;
  describedBy?: string;
}) {
  const metric = cardMetric(layout, sort.sort);
  const cardsOf = (list: ExperimentRow[]) => list.map((r) => (
    <MCard
      key={r.verstr} r={r} layout={layout} metric={metric}
      selected={selected.has(r.verstr)} flash={flash === r.verstr}
      onToggle={onToggle}
    />
  ));
  const sections = rows && sectionsOf(rows);
  return (
    <div className="lb-mcards-wrap">
      <div className="lb-mcards-head">
        {headerCheck && <HeaderCheckbox {...headerCheck} />}
        {metric && <span className="lb-mcards-metric">{metric}</span>}
      </div>
      {sections === undefined ? (
        <p className="lb-mcards-loading" role="status">loading runs…</p>
      ) : (
        <ul className="lb-mcards" role="list" aria-label="experiments" aria-describedby={describedBy}>
          {sections.map((sec, i) => sec.head && groups ? (
            <CardGroup
              key={`group:${sec.head.group.key}`} item={sec.head} more={sec.more}
              layout={layout} metric={metric} groups={groups}
            >
              {cardsOf(sec.rows)}
            </CardGroup>
          ) : (
            <Fragment key={`rows:${i}`}>
              {cardsOf(sec.rows)}
              {sec.more && groups && <CardGroupMore item={sec.more} onMore={groups.onMore} />}
            </Fragment>
          ))}
        </ul>
      )}
    </div>
  );
}
