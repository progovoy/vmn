/** Named leaderboard views, kept in localStorage per workspace/app. A view is
 *  the leaderboard's URL query string minus what is not "view": the
 *  selection (`sel`) and the open create form (`new`). */

export interface SavedView {
  name: string;
  search: string;
}

const EPHEMERAL_PARAMS = ["sel", "new"];

const storageKey = (ws: string, app: string) => `vmn_views:${ws}/${app}`;

const isView = (v: unknown): v is SavedView =>
  typeof v === "object" && v !== null &&
  typeof (v as SavedView).name === "string" && typeof (v as SavedView).search === "string";

/** *search* without the params a saved view must not carry. */
export function viewSearch(search: string): string {
  const p = new URLSearchParams(search);
  EPHEMERAL_PARAMS.forEach((k) => p.delete(k));
  const s = p.toString();
  return s ? `?${s}` : "";
}

export function listViews(ws: string, app: string): SavedView[] {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(storageKey(ws, app)) ?? "[]");
    return Array.isArray(parsed) ? parsed.filter(isView) : [];
  } catch {
    return [];
  }
}

function writeViews(ws: string, app: string, views: SavedView[]) {
  localStorage.setItem(storageKey(ws, app), JSON.stringify(views));
}

/** Save (or overwrite, by name) a view; false when the name is blank. */
export function saveView(ws: string, app: string, name: string, search: string): boolean {
  const trimmed = name.trim();
  if (!trimmed) return false;
  const view = { name: trimmed, search: viewSearch(search) };
  const views = listViews(ws, app);
  const at = views.findIndex((v) => v.name === trimmed);
  if (at >= 0) views[at] = view;
  else views.push(view);
  writeViews(ws, app, views);
  return true;
}

export function deleteView(ws: string, app: string, name: string) {
  writeViews(ws, app, listViews(ws, app).filter((v) => v.name !== name));
}
