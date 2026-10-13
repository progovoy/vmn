/** The board's `Group by ▾` (plan 22 G2, G10): none, the links between runs,
 *  the fields, and — while grouped — the aggregate a group's header shows. */
import { useCallback, useRef, useState } from "react";
import { useAnchorTop } from "../hooks/useAnchorTop";
import { useDismiss } from "../hooks/useDismiss";
import { useMenuKeys } from "../hooks/useMenuKeys";
import { AGGREGATES, NO_GROUP, groupLabel, type Aggregate, type GroupBy, type GroupOption } from "../util/groupBy";
import "./GroupByMenu.css";

function Choice({ label, checked, onPick }: { label: string; checked: boolean; onPick: () => void }) {
  return (
    <button type="button" role="menuitemradio" aria-checked={checked} className="group-by-item" onClick={onPick}>
      {label}
    </button>
  );
}

function Section({ title, options, value, onPick }: {
  title: string; options: readonly GroupOption[]; value: string; onPick: (v: string) => void;
}) {
  return (
    <div role="group" aria-label={title} className="group-by-section">
      <div className="group-by-title" aria-hidden="true">{title}</div>
      {options.map((o) => (
        <Choice key={o.value} label={o.label} checked={o.value === value} onPick={() => onPick(o.value)} />
      ))}
    </div>
  );
}

export default function GroupByMenu({ value, links, fields, onChange, aggregate, onAggregate }: {
  value: GroupBy;
  links: readonly GroupOption[];
  fields: readonly GroupOption[];
  onChange: (group: GroupBy) => void;
  aggregate: Aggregate;
  onAggregate: (agg: Aggregate) => void;
}) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const close = useCallback(() => setOpen(false), []);
  useDismiss(open, close, box, trigger);
  const onMenuKey = useMenuKeys(open, menu, close);
  useAnchorTop(open, trigger, menu, "--group-by-top");

  // A URL group the facets no longer offer stays listed, so it shows checked.
  const known = [...links, ...fields].some((o) => o.value === value);
  const shownFields = known || value === NO_GROUP ? fields : [...fields, { value, label: value }];
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
        {grouped ? `Group by: ${groupLabel(value)} ▾` : "Group by ▾"}
      </button>
      {open && (
        <div className="group-by-menu" role="menu" aria-label="Group by" ref={menu} onKeyDown={onMenuKey}>
          <Choice label="none" checked={!grouped} onPick={() => pick(NO_GROUP)} />
          <Section title="Links" options={links} value={value} onPick={pick} />
          <Section title="Fields" options={shownFields} value={value} onPick={pick} />
          {grouped && (
            <Section
              title="Aggregate" value={aggregate}
              options={AGGREGATES.map((a) => ({ value: a, label: a }))}
              onPick={(a) => onAggregate(a as Aggregate)}
            />
          )}
        </div>
      )}
    </div>
  );
}
