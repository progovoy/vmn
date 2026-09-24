import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { deleteView, listViews, saveView, type SavedView } from "../util/savedViews";

/** Close *onClose* on a mousedown outside *ref*'s element while *active*. */
function useClickOutside(ref: React.RefObject<HTMLElement>, active: boolean, onClose: () => void) {
  useEffect(() => {
    if (!active) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [ref, active, onClose]);
}

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
 *  saved views. Views live in localStorage per workspace/app. */
export default function SavedViews({ ws, app, search, onApply }: {
  ws: string;
  app: string;
  /** The current `location.search`. */
  search: string;
  onApply: (search: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [views, setViews] = useState<SavedView[]>(() => listViews(ws, app));
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const close = useRef(() => setOpen(false)).current;
  useClickOutside(rootRef, open, close);

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
  const remove = (viewName: string) => {
    deleteView(ws, app, viewName);
    setViews(listViews(ws, app));
  };
  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key !== "Escape") return;
    e.stopPropagation();
    setOpen(false);
    buttonRef.current?.focus();
  };

  return (
    <div className="saved-views" ref={rootRef} onKeyDown={onKeyDown}>
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
        </div>
      )}
    </div>
  );
}
