import { Link } from "react-router-dom";
import { runHref } from "../util";
import { groupPicks, type RunPick } from "../util/runSelection";

/** A pick's text: its name, else `@N`, else its verstr. */
const pickText = (p: RunPick) => p.name || (p.idx != null ? `@${p.idx}` : p.verstr);

/** The expanded tray: the picks grouped by job, each linked to its run page
 *  and removable. */
export default function SelectionPicks({ id, picks, base, onRemove }: {
  id: string;
  picks: readonly RunPick[];
  base: string;
  onRemove: (verstr: string) => void;
}) {
  return (
    <ul id={id} className="sel-picks" aria-label="Selected runs">
      {groupPicks(picks).map((g) => (
        <li key={g.job ?? ""} className="sel-picks-group">
          <div role="group" aria-label={g.label}>
            <span className="sel-picks-job" aria-hidden title={g.job ?? undefined}>{g.label}</span>
            <ul className="sel-picks-runs">
              {g.picks.map((p) => (
                <li key={p.verstr} className="sel-pick">
                  <Link to={runHref(base, p.verstr)} title={p.verstr}>{pickText(p)}</Link>
                  <button
                    className="sel-pick-remove" aria-label={`Remove ${pickText(p)}`} title="Remove from the selection"
                    onClick={() => onRemove(p.verstr)}
                  >
                    ✕
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </li>
      ))}
    </ul>
  );
}
