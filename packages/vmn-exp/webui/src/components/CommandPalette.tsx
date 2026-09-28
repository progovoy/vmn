import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, appTag } from "../api";
import type { AppRow, ExperimentRow, Workspace } from "../types";
import { relTime, runHref } from "../util";
import { useDebounce } from "../hooks/useDebounce";
import { runSearchQuery } from "../util/searchQuery";

interface Item {
  kind: "page" | "action" | "run" | "app" | "workspace";
  label: string;
  hint?: string;
  to: string;
}

const RUNS = 20;
/** The newest runs stay fresh this long, so reopening ⌘K costs no request. */
const RECENT_STALE_MS = 30_000;

/** The runs the palette offers: the newest until something is typed, then a
 *  server search over every run — never just a filter of the newest 20. */
function usePaletteRuns(ws: string | undefined, app: string | undefined, needle: string) {
  const client = useQueryClient();
  const scoped = Boolean(ws && app);
  const recent = useQuery<ExperimentRow[]>({
    queryKey: ["recent-runs", ws, app],
    queryFn: () => api.recentExperiments(ws!, app!, RUNS),
    enabled: scoped,
    staleTime: RECENT_STALE_MS,
  }, client);
  const typed = useDebounce(needle, 250);
  const search = useQuery<ExperimentRow[]>({
    queryKey: ["run-search", ws, app, typed],
    queryFn: () =>
      api.experimentsPaged(ws!, app!, { query: runSearchQuery(typed), limit: RUNS }).then((p) => p.rows),
    enabled: scoped && Boolean(typed),
    staleTime: RECENT_STALE_MS,
    placeholderData: keepPreviousData,
  }, client);
  if (needle && typed && search.data) return { runs: search.data, searched: true };
  return { runs: recent.data ?? [], searched: false };
}

const PAGES: [string, string][] = [
  ["Experiments", ""],
  ["Snapshots", "/snapshots"],
  ["Stamp tree", "/tree"],
  ["Actions", "/actions"],
];

export default function CommandPalette({ ws, app, workspaces, apps, onClose }: {
  ws?: string;
  app?: string;
  workspaces: Workspace[];
  apps: AppRow[];
  onClose: () => void;
}) {
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

  useEffect(() => inputRef.current?.focus(), []);

  const needle = q.trim().toLowerCase();
  const { runs, searched } = usePaletteRuns(ws, app, q.trim());

  const items = useMemo<Item[]>(() => {
    const base = ws && app ? `/ws/${ws}/app/${appTag(app)}` : null;
    const out: Item[] = [];
    if (base) {
      PAGES.forEach(([label, path]) =>
        out.push({ kind: "page", label, hint: app, to: `${base}${path}` })
      );
      out.push({
        kind: "action", label: "New experiment",
        hint: "capture the working state", to: `${base}?new=1`,
      });
    }
    runs.forEach((r) =>
      base && out.push({
        kind: "run",
        label: r.verstr,
        hint: r.note || relTime(r.timestamp),
        to: runHref(base, r.verstr),
      })
    );
    if (ws) {
      apps.forEach((a) =>
        a.name !== app && out.push({
          kind: "app", label: a.name,
          hint: `${a.experiments} experiments`,
          to: `/ws/${ws}/app/${appTag(a.name)}`,
        })
      );
    }
    workspaces.forEach((w) =>
      w.name !== ws && out.push({
        kind: "workspace", label: w.name,
        hint: w.kind === "s3" ? "s3" : w.path, to: `/ws/${w.name}`,
      })
    );
    return out;
  }, [ws, app, apps, workspaces, runs]);

  // Server search results already matched; everything else filters here.
  const shown = useMemo(() => {
    if (!needle) return items;
    return items.filter((i) =>
      (searched && i.kind === "run") ||
      `${i.kind} ${i.label} ${i.hint ?? ""}`.toLowerCase().includes(needle)
    );
  }, [items, needle, searched]);

  useEffect(() => setActive(0), [q]);

  const go = (item: Item) => {
    navigate(item.to);
    onClose();
  };

  // Document-level so arrows/enter/escape work even if the input loses focus.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      else if (e.key === "ArrowDown") {
        e.preventDefault();
        setActive((a) => Math.min(a + 1, shown.length - 1));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setActive((a) => Math.max(a - 1, 0));
      } else if (e.key === "Enter" && shown[active]) {
        e.preventDefault();
        navigate(shown[active].to);
        onClose();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [shown, active, navigate, onClose]);

  return (
    <div className="palette-veil" onMouseDown={onClose}>
      <div className="palette" onMouseDown={(e) => e.stopPropagation()}>
        <input
          ref={inputRef}
          placeholder="Jump to a run, app, page, or workspace…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <div className="palette-list">
          {shown.length === 0 && <div className="palette-empty">No matches.</div>}
          {shown.map((item, i) => (
            <div
              key={`${item.kind}:${item.to}`}
              className={`palette-item${i === active ? " active" : ""}`}
              onMouseEnter={() => setActive(i)}
              onClick={() => go(item)}
            >
              <span className="kind">{item.kind}</span>
              <span className={item.kind === "run" || item.kind === "app" ? "mono" : ""}>
                {item.label}
              </span>
              {item.hint && <span className="hint">{item.hint}</span>}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
