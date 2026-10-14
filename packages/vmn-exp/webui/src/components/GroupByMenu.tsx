/** The board's `Group by ▾` (plan 22 G2, G10, F13): none, the links between
 *  runs, the fields, and — while grouped — what orders the groups (the
 *  aggregate, or a count of their runs) and the aggregate a header shows. */
import { useCallback, useRef, useState } from "react";
import { useAnchorTop } from "../hooks/useAnchorTop";
import { useDismiss } from "../hooks/useDismiss";
import { useMenuKeys } from "../hooks/useMenuKeys";
import { AGGREGATES, NO_GROUP, groupLabel, type Aggregate, type GroupBy, type GroupOption } from "../util/groupBy";
import { GROUP_SORTS } from "../util/groupCountSort";
import "./GroupByMenu.css";

function Choice({ label, checked, onPick }: { label: string; checked: boolean; onPick: () => void }) {
  return (
    <button type="button" role="menuitemradio" aria-checked={checked} className="group-by-item" onClick={onPick}>
      {label}
    </button>
  );
}

function Section<V extends string | null>({ title, options, value, onPick }: {
  title: string; options: readonly { value: V; label: string }[]; value: V; onPick: (v: V) => void;
}) {
  return (
    <div role="group" aria-label={title} className="group-by-section">
      <div className="group-by-title" aria-hidden="true">{title}</div>
      {options.map((o) => (
        <Choice key={o.value ?? ""} label={o.label} checked={o.value === value} onPick={() => onPick(o.value)} />
      ))}
    </div>
  );
}

export default function GroupByMenu({
  value, links, fields, onChange, aggregate, onAggregate, groupSort, onGroupSort, viewGroup = NO_GROUP,
}: {
  value: GroupBy;
  /** The grouping the view itself is (the Jobs view: parent run, plan 23
   *  §3.4): shown checked while *value* is none, with no groups to sort. */
  viewGroup?: GroupBy;
  links: readonly GroupOption[];
  fields: readonly GroupOption[];
  onChange: (group: GroupBy) => void;
  aggregate: Aggregate;
  onAggregate: (agg: Aggregate) => void;
  /** The count the groups are sorted by (`c:<name>`), null for the aggregate. */
  groupSort: string | null;
  onGroupSort: (sort: string | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const close = useCallback(() => setOpen(false), []);
  useDismiss(open, close, box, trigger);
  const onMenuKey = useMenuKeys(open, menu, close);
  useAnchorTop(open, trigger, menu, "--group-by-top");

  const shown = value === NO_GROUP ? viewGroup : value;
  // A URL group the facets no longer offer stays listed, so it shows checked.
  const known = [...links, ...fields].some((o) => o.value === shown);
  const shownFields = known || shown === NO_GROUP ? fields : [...fields, { value: shown, label: shown }];
  const pick = (group: GroupBy) => {
    close();
    trigger.current?.focus();
    onChange(group);
  };
  const grouped = value !== NO_GROUP;

  return (
    <div className="group-by" ref={box}>
      <button
        ref={trigger} type="button" aria-haspopup="menu" aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        {shown !== NO_GROUP ? `Group by: ${groupLabel(shown)} ▾` : "Group by ▾"}
      </button>
      {open && (
        <div className="group-by-menu" role="menu" aria-label="Group by" ref={menu} onKeyDown={onMenuKey}>
          <Choice label="none" checked={shown === NO_GROUP} onPick={() => pick(NO_GROUP)} />
          <Section title="Links" options={links} value={shown} onPick={pick} />
          <Section title="Fields" options={shownFields} value={shown} onPick={pick} />
          {grouped && (
            <div className="group-by-footer">
              <Section title="Sort groups" value={groupSort} options={GROUP_SORTS} onPick={onGroupSort} />
              <Section
                title="Aggregate" value={aggregate}
                options={AGGREGATES.map((a) => ({ value: a, label: a }))}
                onPick={(a) => onAggregate(a as Aggregate)}
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
