/** An outer run's tree (plan 28 N6): its runs nested by parent, each node
 *  with its subtree's run bar, worst attention, best value, its duration
 *  against its siblings and the columns the app's `tree_columns` name for
 *  its `tags.kind`. Children load as a node opens; the nodes the server
 *  marks `open` (attention or live runs below) start open, healthy ones
 *  folded, so a 10k-run launch opens as a handful of rows; under a filter,
 *  each level keeps the nodes whose subtree passes it and those with a
 *  passing run below start open. Virtualized like
 *  the board; embedded, its rows flow inline in the scroll box around it
 *  (one scrollbar), virtualized against that box. A WAI-ARIA tree grid: Up/Down move, Right opens (or steps
 *  into), Left folds (or steps out), Enter toggles. */
import { useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent, type RefObject } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { TreeFilter } from "../../apiTree";
import { appTag } from "../../http";
import { useFillHeight } from "../../hooks/useFillHeight";
import { useTreeChildren } from "../../hooks/useTreeChildren";
import { useMetricsSchema } from "../../queries";
import type { AttentionEntry } from "../../shell/contracts";
import { metricGoal } from "../../util";
import { itemKey, type TreeItem } from "../../util/treeItems";
import { mainMetric } from "../Experiments/jobColumns";
import type { JobContext } from "../Experiments/JobCells";
import JobTreeRow, { TREE_COLUMNS, TREE_ROW_HEIGHT } from "./JobTreeRow";
import "../leaderboardTable.css";
import "../Experiments/jobsTable.css";
import "./jobTree.css";

/** An opened tree's height inside an Outer runs row before it is measured. */
export const EMBEDDED_HEIGHT = TREE_ROW_HEIGHT * 10 + 36;

export default function JobTree({ ws, app, verstr, name, attention, embedded = false, filter }: {
  ws: string; app: string; verstr: string;
  /** The outer run's name, naming the tree. */
  name?: string;
  /** The app's attention parts: the labels and levels of the counts. */
  attention?: readonly AttentionEntry[];
  /** Inside an Outer runs row: no scroll box of its own, it grows in the board's. */
  embedded?: boolean;
  /** The Runs tab's filters: each level keeps the nodes whose subtree passes. */
  filter?: TreeFilter;
}) {
  const tree = useTreeChildren(ws, app, verstr, filter);
  const schema = useMetricsSchema(ws, app);
  const metric = mainMetric(tree.rows, schema);
  const ctx: JobContext = useMemo(() => ({
    runBase: `/ws/${ws}/app/${appTag(app)}`, metric, goal: metric ? metricGoal(schema, metric) : null,
    attention,
  }), [ws, app, metric, schema, attention]);
  const parentRef = useRef<HTMLDivElement>(null);
  const cardRef = useRef<HTMLDivElement>(null);
  const bodyRef = useRef<HTMLTableSectionElement>(null);
  const unfilled = useRef<HTMLDivElement>(null);
  useFillHeight(embedded ? unfilled : parentRef);
  const outer = useOuterScroll(cardRef, bodyRef, embedded);
  const margin = embedded ? outer.margin : 0;
  const { items } = tree;
  const virtualizer = useVirtualizer({
    count: items.length, getScrollElement: () => (embedded ? outer.box.current : parentRef.current),
    estimateSize: () => TREE_ROW_HEIGHT, overscan: 20, scrollMargin: margin,
  });
  const keys = useTreeKeys(parentRef, items, tree.toggle, (i) => virtualizer.scrollToIndex?.(i));
  const virtual = virtualizer.getVirtualItems();
  const last = virtual[virtual.length - 1];

  return (
    <div className="card flush job-tree-card" ref={cardRef}>
      <div
        className="tbl-scroll" ref={parentRef}
        style={embedded ? undefined : { maxHeight: "calc(100vh - 340px)", overflow: "auto" }}
      >
        <table role="treegrid" aria-label={`runs of ${name ?? verstr}`} className="lb-table job-tree">
          <colgroup>{TREE_COLUMNS.map((c) => <col key={c.id} style={{ width: c.width }} />)}</colgroup>
          <thead>
            <tr>{TREE_COLUMNS.map((c) => <th key={c.id} role="columnheader" className={c.numeric ? "num" : undefined}>{c.label}</th>)}</tr>
          </thead>
          <tbody ref={bodyRef} onKeyDown={keys.onKeyDown}>
            {virtual.length > 0 && virtual[0].start > margin && <tr aria-hidden style={{ height: virtual[0].start - margin }} />}
            {virtual.map((v) => (
              <JobTreeRow
                key={itemKey(items[v.index])} item={items[v.index]} index={v.index}
                isActive={v.index === keys.active} ctx={ctx} columns={tree.columns}
                onToggle={tree.toggle} onMore={tree.more}
              />
            ))}
            {last && virtualizer.getTotalSize() > last.end - margin && (
              <tr aria-hidden style={{ height: virtualizer.getTotalSize() - (last.end - margin) }} />
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** The nearest box around *el* (itself included) that scrolls vertically. */
function scrollParent(el: HTMLElement | null): HTMLElement | null {
  for (let node = el; node; node = node.parentElement) {
    const st = getComputedStyle(node);
    if (/auto|scroll/.test(`${st.overflow} ${st.overflowY}`)) return node;
  }
  return null;
}

/** An embedded tree's scroll box (the one around its card) and where its
 *  rows start in that box's content, re-read each render. */
function useOuterScroll(card: RefObject<HTMLElement>, body: RefObject<HTMLElement>, on: boolean) {
  const box = useRef<HTMLElement | null>(null);
  const [margin, setMargin] = useState(0);
  useLayoutEffect(() => {
    if (!on) return;
    box.current = scrollParent(card.current?.parentElement ?? null);
    const scroller = box.current;
    if (!scroller || !body.current) return;
    setMargin(body.current.getBoundingClientRect().top - scroller.getBoundingClientRect().top + scroller.scrollTop);
  });
  return { box, margin };
}

/** The tree grid's roving tab stop and keys over `tr[data-tree-index]` rows. */
function useTreeKeys(
  container: React.RefObject<HTMLElement>, items: readonly TreeItem[],
  toggle: (verstr: string, open: boolean) => void, scrollTo: (i: number) => void,
) {
  const [active, setActive] = useState(0);
  const focusWanted = useRef<number | null>(null);
  const current = Math.min(active, Math.max(0, items.length - 1));

  useLayoutEffect(() => {
    if (focusWanted.current === null) return;
    const i = focusWanted.current;
    focusWanted.current = null;
    container.current?.querySelector<HTMLElement>(`tr[data-tree-index="${i}"]`)?.focus();
  });

  const focus = (i: number) => {
    const next = Math.max(0, Math.min(items.length - 1, i));
    focusWanted.current = next;
    setActive(next);
    scrollTo(next);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLElement>) => {
    const row = (e.target as HTMLElement).closest<HTMLElement>("tr[data-tree-index]");
    if (!row || e.ctrlKey || e.metaKey || e.altKey) return;
    const index = Number(row.dataset.treeIndex);
    const it = items[index];
    const node = it?.kind === "node" ? it : null;
    const act = (run: () => void) => { e.preventDefault(); e.stopPropagation(); run(); };
    switch (e.key) {
      case "ArrowDown": return act(() => focus(index + 1));
      case "ArrowUp": return act(() => focus(index - 1));
      case "Home": return act(() => focus(0));
      case "End": return act(() => focus(items.length - 1));
      case "ArrowRight":
        if (!node?.expandable) return;
        return act(() => (node.expanded ? focus(index + 1) : (toggle(node.row.verstr, true), focus(index))));
      case "ArrowLeft":
        if (node?.expanded) return act(() => { toggle(node.row.verstr, false); focus(index); });
      {
        const up = items.findIndex((x) => x.kind === "node" && x.row.verstr === it?.parent);
        return up < 0 ? undefined : act(() => focus(up));
      }
      case "Enter":
        if (row !== e.target || !node?.expandable) return;
        return act(() => { toggle(node.row.verstr, !node.expanded); focus(index); });
    }
  };

  return { active: current, onKeyDown };
}
