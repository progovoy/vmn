/** One row of an outer run's tree (plan 28 N6): a node (indented by its
 *  depth, its expander, its run bar or status, worst attention, best value,
 *  duration against its siblings and its kind's columns), a `+N more` row
 *  or a loading row. */
import { memo } from "react";
import { Link } from "react-router-dom";
import JobProgress from "../../components/JobProgress";
import StatusPill from "../../components/StatusPill";
import { fmtCount, fmtDuration, runHref } from "../../util";
import { cellText, kindColumns, worstAttention, type TreeItem, type TreeNodeItem } from "../../util/treeItems";
import TreeToggle from "../../components/TreeToggle";
import { AttentionChip, BestValue, type JobContext } from "../Experiments/JobCells";
import { durationText, headStatus } from "../LeaderboardRow";

export const TREE_ROW_HEIGHT = 40;
const INDENT_PX = 18;

interface TreeColumn { id: string; label: string; width: number; numeric?: boolean }

export const TREE_COLUMNS: readonly TreeColumn[] = [
  { id: "name", label: "run", width: 340 },
  { id: "status", label: "status · progress", width: 300 },
  { id: "attention", label: "attention", width: 150 },
  { id: "best", label: "best", width: 130, numeric: true },
  { id: "duration", label: "duration", width: 150, numeric: true },
  { id: "fields", label: "fields", width: 280 },
];

interface RowProps {
  item: TreeItem;
  index: number;
  /** The grid's one tab stop (roving tabindex). */
  isActive: boolean;
  ctx: JobContext;
  columns?: Record<string, string[]>;
  onToggle: (verstr: string, open: boolean) => void;
  onMore: (parent: string) => void;
}

function Indented({ depth, children }: { depth: number; children: React.ReactNode }) {
  return <div className="tree-name" style={{ paddingLeft: depth * INDENT_PX }}>{children}</div>;
}

function NameCell({ it, ctx, onToggle }: { it: TreeNodeItem; ctx: JobContext; onToggle: RowProps["onToggle"] }) {
  const { row: r } = it;
  const label = r.name || r.verstr;
  return (
    <Indented depth={it.depth}>
      {it.expandable
        ? <TreeToggle label={label} expanded={it.expanded} tabIndex={-1} onToggle={() => onToggle(r.verstr, !it.expanded)} />
        : <span className="tree-toggle-gap" aria-hidden />}
      <Link className={`run-link${r.name ? " run-name" : " mono"}`} to={runHref(ctx.runBase, r.verstr)} title={r.verstr}>
        {label}
      </Link>
      {r.tags?.kind && <span className="tree-kind">{r.tags.kind}</span>}
    </Indented>
  );
}

function StatusCell({ it }: { it: TreeNodeItem }) {
  const r = it.row;
  if (r.job) return <JobProgress job={r.job} inline />;
  const status = headStatus(r);
  return status ? (
    <StatusPill status={status} exitCode={r.exit_code} durationSec={r.duration_sec}
      staleSec={r.stale_sec} errorSummary={r.error_summary} />
  ) : null;
}

function AttentionCell({ it, ctx }: { it: TreeNodeItem; ctx: JobContext }) {
  const worst = worstAttention(it.row, ctx.attention ?? []);
  return worst && <AttentionChip entry={worst} count={worst.count} />;
}

function DurationCell({ it }: { it: TreeNodeItem }) {
  const { duration_sec: sec, duration_ratio: ratio } = it.row;
  const [ratioText, ratioTitle] = durationText("duration_ratio", ratio);
  return (
    <span className="tree-duration">
      {sec != null && <span>{fmtDuration(sec)}</span>}
      {ratio != null && <span className={`tree-ratio${ratio >= 2 ? " slow" : ""}`} title={ratioTitle}>{ratioText}</span>}
    </span>
  );
}

function FieldsCell({ it, columns }: { it: TreeNodeItem; columns?: Record<string, string[]> }) {
  return (
    <>
      {kindColumns(it.row, columns).map((key) => {
        const [label, text] = cellText(it.row, key);
        return <span key={key} className="tree-field"><span className="muted">{label}</span> {text}</span>;
      })}
    </>
  );
}

function NodeRow({ it, index, isActive, ctx, columns, onToggle }: Omit<RowProps, "item" | "onMore"> & { it: TreeNodeItem }) {
  const cells: Record<string, React.ReactNode> = {
    name: <NameCell it={it} ctx={ctx} onToggle={onToggle} />,
    status: <StatusCell it={it} />,
    attention: <AttentionCell it={it} ctx={ctx} />,
    best: <BestValue r={it.row} ctx={ctx} />,
    duration: <DurationCell it={it} />,
    fields: <FieldsCell it={it} columns={columns} />,
  };
  return (
    <tr
      role="row" className={`row tree-row${it.row.archived ? " archived" : ""}`}
      style={{ height: TREE_ROW_HEIGHT }} data-tree-index={index} tabIndex={isActive ? 0 : -1}
      aria-level={it.depth + 1} aria-posinset={it.posinset} aria-setsize={it.setsize}
      aria-expanded={it.expandable ? it.expanded : undefined}
    >
      {TREE_COLUMNS.map((c) => (
        <td key={c.id} role="gridcell" data-col-id={c.id} className={c.numeric ? "num" : undefined}>
          {cells[c.id]}
        </td>
      ))}
    </tr>
  );
}

function JobTreeRow({ item, index, isActive, ctx, columns, onToggle, onMore }: RowProps) {
  if (item.kind === "node") {
    return <NodeRow it={item} index={index} isActive={isActive} ctx={ctx} columns={columns} onToggle={onToggle} />;
  }
  return (
    <tr role="row" className="tree-row tree-aux" style={{ height: TREE_ROW_HEIGHT }} data-tree-index={index}
      tabIndex={isActive ? 0 : -1} aria-level={item.depth + 1}>
      <td role="gridcell" colSpan={TREE_COLUMNS.length}>
        <Indented depth={item.depth}>
          <span className="tree-toggle-gap" aria-hidden />
          {item.kind === "more"
            ? <button type="button" className="tree-more" onClick={() => onMore(item.parent)}>{`+${fmtCount(item.remaining)} more`}</button>
            : <span className="muted">loading…</span>}
        </Indented>
      </td>
    </tr>
  );
}

export default memo(JobTreeRow);
