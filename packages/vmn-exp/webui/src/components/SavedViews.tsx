import { useCallback, useRef, useState } from "react";
import { useDismiss } from "../hooks/useDismiss";
import { deleteView, listViews, saveView, type SavedView } from "../util/savedViews";
import { TeamSave, TeamViewList, type TeamViewItem } from "./TeamViews";

function ViewList({ views, onApply, onDelete }: {
  views: SavedView[];
  onApply: (v: SavedView) => void;
  onDelete: (name: string) => void;
}) {
  if (views.length === 0) return <div className="saved-views-empty">No saved views yet.</div>;
  return (
    <ul className="saved-views-list">
      {views.map((v) => (
        <li key={v.name} className="saved-views-item">
          <button role="menuitem" className="link" onClick={() => onApply(v)}>{v.name}</button>
          <button
            className="saved-views-del"
            aria-label={`Delete view ${v.name}`}
            onClick={() => onDelete(v.name)}
          >
            ×
          </button>
        </li>
      ))}
    </ul>
  );
}

/** Name and save the leaderboard's current URL state; list, apply and delete
 *  saved views. Views live in localStorage per workspace/app. The app's
 *  *team* views (plan 28 P4) are listed above them, read-only; with
 *  *onSaveTeam* (an editor) the current view can be saved for the team. */
export default function SavedViews({ ws, app, search, onApply, team = [], onApplyTeam, onSaveTeam }: {
  ws: string;
  app: string;
  /** The current `location.search`. */
  search: string;
  onApply: (search: string) => void;
  team?: readonly TeamViewItem[];
  /** Apply a team view (else *onApply*). */
  onApplyTeam?: (search: string) => void;
  onSaveTeam?: (name: string, isDefault: boolean) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [views, setViews] = useState<SavedView[]>(() => listViews(ws, app));
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const close = useCallback(() => setOpen(false), []);
  useDismiss(open, close, rootRef, buttonRef);

  const toggle = () => {
    if (!open) setViews(listViews(ws, app));
    setOpen((o) => !o);
  };
  const save = () => {
    if (!saveView(ws, app, name, search)) return;
    setName("");
    setViews(listViews(ws, app));
  };
  const apply = (v: SavedView) => {
    setOpen(false);
    onApply(v.search);
  };
  const applyTeam = (v: TeamViewItem) => {
    setOpen(false);
    (onApplyTeam ?? onApply)(v.search);
  };
  const remove = (viewName: string) => {
    deleteView(ws, app, viewName);
    setViews(listViews(ws, app));
  };

  return (
    <div className="saved-views" ref={rootRef}>
      <button
        ref={buttonRef}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={toggle}
      >
        Views ▾
      </button>
      {open && (
        <div className="col-picker saved-views-menu" role="menu">
          {team.length > 0 && (
            <>
              <TeamViewList views={team} onApply={applyTeam} />
              <div className="col-picker-title">My views</div>
            </>
          )}
          <ViewList views={views} onApply={apply} onDelete={remove} />
          <div className="col-picker-title">Save current view…</div>
          <div className="saved-views-save">
            <input
              type="text"
              aria-label="View name"
              placeholder="View name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") save(); }}
              autoFocus
            />
            <button className="primary" onClick={save}>Save</button>
          </div>
          {onSaveTeam && <TeamSave name={name} onSave={onSaveTeam} onSaved={() => setName("")} />}
        </div>
      )}
    </div>
  );
}
