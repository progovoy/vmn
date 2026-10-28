/** The Views menu's team part (plan 28 P4): the app's team views, read-only
 *  (they live in its settings), and an editor's "Save for team". */
import { useState } from "react";
import type { TeamView } from "../util/teamViews";

export type TeamViewItem = Pick<TeamView, "name" | "search"> & { default?: boolean };

export function TeamViewList({ views, onApply }: {
  views: readonly TeamViewItem[];
  onApply: (v: TeamViewItem) => void;
}) {
  return (
    <div role="group" aria-labelledby="team-views-title">
      <div className="col-picker-title" id="team-views-title">Team views</div>
      <ul className="saved-views-list">
        {views.map((v) => (
          <li key={v.name} className="saved-views-item">
            <button role="menuitem" className="link" onClick={() => onApply(v)} title={v.search || "the bare page"}>
              {v.name}
            </button>
            {v.default && <span className="muted saved-views-default">default</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Save the current view under *name* for the team; *onSaved* clears it. */
export function TeamSave({ name, onSave, onSaved }: {
  name: string;
  onSave: (name: string, isDefault: boolean) => Promise<void>;
  onSaved: () => void;
}) {
  const [isDefault, setDefault] = useState(false);
  const [state, setState] = useState<{ saving?: boolean; saved?: boolean; error?: string }>({});
  const save = () => {
    const trimmed = name.trim();
    if (!trimmed) return;
    setState({ saving: true });
    onSave(trimmed, isDefault).then(
      () => { setState({ saved: true }); onSaved(); },
      (e: unknown) => setState({ error: e instanceof Error ? e.message : String(e) }),
    );
  };
  return (
    <>
      <div className="saved-views-save saved-views-team">
        <label className="muted">
          <input type="checkbox" checked={isDefault} onChange={(e) => setDefault(e.target.checked)} />
          as this page&apos;s default
        </label>
        <button onClick={save} disabled={state.saving}>Save for team</button>
      </div>
      {state.saved && <div className="muted">Saved for the team</div>}
      {state.error && <div className="error" role="alert">{state.error}</div>}
    </>
  );
}
