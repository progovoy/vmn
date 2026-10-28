/** An app's team views (plan 28 P4): settings/conf `experiment.ui.views`,
 *  served on its status. A view is a URL query string for one page: the
 *  Outer runs view (`jobs`, Single runs too), All runs (`runs`) or an outer
 *  run's page (`job`); one per page may be its `default`. */

import { EPHEMERAL_PARAMS, viewSearch } from "./savedViews";

export type ViewPage = "jobs" | "runs" | "job";

export interface TeamView {
  name: string;
  page: ViewPage;
  /** `?…`, or "" for the bare page. */
  search: string;
  default: boolean;
}

/** Params that say where the page is (which view, kind or tab), not what it shows. */
const PLACE_PARAMS = ["view", "kind", "tab"];

export const pageViews = (views: readonly TeamView[] | undefined, page: ViewPage): TeamView[] =>
  (views ?? []).filter((v) => v.page === page);

export const defaultViewOf = (views: readonly TeamView[] | undefined, page: ViewPage) =>
  pageViews(views, page).find((v) => v.default);

/** Whether *search* carries anything a view sets (not just where the page is). */
export function hasViewParams(search: string): boolean {
  const skip = new Set([...PLACE_PARAMS, ...EPHEMERAL_PARAMS]);
  return [...new URLSearchParams(search).keys()].some((k) => !skip.has(k));
}

/** *search* plus the place params of *current* it leaves out, so a view
 *  written without `tab=runs` stays on the tab it was applied from. */
export function placedSearch(current: string, search: string): string {
  const next = new URLSearchParams(search);
  const here = new URLSearchParams(current);
  PLACE_PARAMS.forEach((k) => {
    const v = here.get(k);
    if (v !== null && !next.has(k)) next.set(k, v);
  });
  return viewSearch(next.toString());
}

type Settings = Record<string, unknown>;
type StoredView = Omit<TeamView, "default"> & { default?: boolean };

/** *settings* with *view* among its `ui.views` (replacing the page's view of
 *  that name); a default one takes the page's default from the others. */
export function withTeamView(settings: Settings, view: TeamView): Settings {
  const ui = (settings.ui ?? {}) as Settings;
  const stored: StoredView = { name: view.name, page: view.page, search: view.search };
  if (view.default) stored.default = true;
  const same = (v: StoredView) => v.page === view.page && v.name === view.name;
  const views = ((ui.views ?? []) as StoredView[]).map((v) => {
    if (same(v)) return stored;
    if (!view.default || v.page !== view.page || !("default" in v)) return v;
    const { default: _dropped, ...rest } = v;
    return rest;
  });
  if (!views.some(same)) views.push(stored);
  return { ...settings, ui: { ...ui, views } };
}
