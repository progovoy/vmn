import { Link } from "react-router-dom";
import { runHref } from "../util";
import { groupPicks, type PickGroup, type RunPick } from "../util/runSelection";
import { describeGroup, type QueryGroup } from "../util/selectionGroups";

/** A pick's text: its name, else `@N`, else its verstr. */
const pickText = (p: RunPick) => p.name || (p.idx != null ? `@${p.idx}` : p.verstr);

interface Section extends PickGroup {
  queries: QueryGroup[];
}

/** The picks by job, each job's selected queries with its picks. */
function sectionsOf(picks: readonly RunPick[], groups: readonly QueryGroup[]): Section[] {
  const sections: Section[] = groupPicks(picks).map((g) => ({ ...g, queries: [] }));
  for (const q of groups) {
    const at = sections.find((s) => s.job === q.job);
    if (at) at.queries.push(q);
    else sections.splice(sections.filter((s) => s.job !== null).length, 0,
      { job: q.job, label: q.label, picks: [], queries: [q] });
  }
  return sections;
}

function RemoveButton({ text, onClick }: { text: string; onClick: () => void }) {
  return (
    <button className="sel-pick-remove" aria-label={`Remove ${text}`} title="Remove from the selection" onClick={onClick}>
      ✕
    </button>
  );
}

/** The expanded tray: the picks grouped by job, each linked to its run page
 *  and removable; a selected query is one removable entry of its job. */
export default function SelectionPicks({ id, picks, groups = [], base, onRemove, onRemoveGroup }: {
  id: string;
  picks: readonly RunPick[];
  groups?: readonly QueryGroup[];
  base: string;
  onRemove: (verstr: string) => void;
  onRemoveGroup?: (group: QueryGroup) => void;
}) {
  return (
    <ul id={id} className="sel-picks" aria-label="Selected runs">
      {sectionsOf(picks, groups).map((g) => (
        <li key={g.job ?? ""} className="sel-picks-group">
          <div role="group" aria-label={g.label}>
            <span className="sel-picks-job" aria-hidden title={g.job ?? undefined}>{g.label}</span>
            <ul className="sel-picks-runs">
              {g.queries.map((q) => (
                <li key={`${q.q}\u0000${q.status}`} className="sel-pick">
                  <span>{describeGroup(q)}</span>
                  {onRemoveGroup && <RemoveButton text={describeGroup(q)} onClick={() => onRemoveGroup(q)} />}
                </li>
              ))}
              {g.picks.map((p) => (
                <li key={p.verstr} className="sel-pick">
                  <Link to={runHref(base, p.verstr)} title={p.verstr}>{pickText(p)}</Link>
                  <RemoveButton text={pickText(p)} onClick={() => onRemove(p.verstr)} />
                </li>
              ))}
            </ul>
          </div>
        </li>
      ))}
    </ul>
  );
}
