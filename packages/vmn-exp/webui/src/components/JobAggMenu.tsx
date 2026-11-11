/** The Outer runs value column's menu (plan 31 §2): the aggregate, the
 *  units it is over, each unit's value (its subtree best or its own) and
 *  the metric, in the Group by menu's sections, whether units carrying a
 *  field count at any depth (plan 35 §2), plus the app's default.
 *  Picks stay open, like the group Aggregate. */
import { useCallback, useRef, useState } from "react";
import { useAnchorTop } from "../hooks/useAnchorTop";
import { useDismiss } from "../hooks/useDismiss";
import { useMenuKeys } from "../hooks/useMenuKeys";
import type { Goal } from "../util";
import { AGGREGATES } from "../util/groupBy";
import { JOB_AGG_SOURCES, carriedBy, tailLabel, type JobAggParams, type JobAggPart } from "../util/jobAggregate";
import { Section } from "./GroupByMenu";
import "./GroupByMenu.css";

const asOptions = (values: readonly string[]) => values.map((value) => ({ value, label: value }));
/** Units carrying a field: the nearest on each branch, or every one (plan 35 §2). */
const NESTED_OPTIONS = [{ value: "0", label: "nearest only" }, { value: "1", label: "at any depth" }];
/** *values* with *current* kept, so a URL value the facets lack shows checked. */
const withCurrent = (values: readonly string[], current: string | null) =>
  current && !values.includes(current) ? [...values, current] : values;

export default function JobAggMenu({ shown, goal, byOptions, metricOptions, onPick, onReset }: {
  /** The effective choice: the URL's, else what the rows answered (null: unknown). */
  shown: JobAggParams;
  /** The goal the tails' percentiles follow. */
  goal: Goal;
  byOptions: readonly string[];
  metricOptions: readonly string[];
  onPick: (part: JobAggPart, value: string) => void;
  /** Back to the app's `experiment.ui.job_aggregate`. */
  onReset: () => void;
}) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const close = useCallback(() => setOpen(false), []);
  useDismiss(open, close, box, trigger);
  const onMenuKey = useMenuKeys(open, menu, close);
  useAnchorTop(open, trigger, menu, "--job-agg-top", "--job-agg-left");
  const pick = (part: JobAggPart) => (v: string | null) => { if (v) onPick(part, v); };

  return (
    <div className="group-by job-agg" ref={box}>
      <button
        ref={trigger} type="button" className="job-agg-trigger" aria-haspopup="menu" aria-expanded={open}
        aria-label="Pick the value's aggregate" title="Pick the value's aggregate"
        onClick={() => setOpen((o) => !o)}
      >
        ▾
      </button>
      {open && (
        <div className="group-by-menu job-agg-menu" role="menu" aria-label="Value aggregate" ref={menu} onKeyDown={onMenuKey}>
          <Section
            title="Aggregate" value={shown.agg}
            options={AGGREGATES.map((a) => ({ value: a, label: tailLabel(a, goal) }))}
            onPick={pick("agg")}
          />
          <Section title="By" value={shown.by} options={asOptions(withCurrent(byOptions, shown.by))} onPick={pick("by")} />
          <Section title="Value" value={shown.value} options={asOptions(JOB_AGG_SOURCES)} onPick={pick("value")} />
          <Section
            title="Metric" value={shown.metric}
            options={asOptions(withCurrent(metricOptions, shown.metric))} onPick={pick("metric")}
          />
          {carriedBy(shown.by) && (
            <Section
              title="Nested" value={shown.nested == null ? null : shown.nested ? "1" : "0"}
              options={NESTED_OPTIONS} onPick={pick("nested")}
            />
          )}
          <button type="button" role="menuitem" className="group-by-item" onClick={() => { close(); onReset(); }}>
            app default
          </button>
        </div>
      )}
    </div>
  );
}
