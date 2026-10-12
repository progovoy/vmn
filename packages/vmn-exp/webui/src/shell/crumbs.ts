/** The breadcrumb trail after ContextRoot (plan 19 §1.4): lowercase CLI
 *  nouns, identifiers in mono, the leaf last. Pure, so titles and tests share it. */
import { midTruncate } from "../util/midTruncate";
import type { Crumb, CrumbInput, RouteId, RunLabel } from "./contracts";

const RUN_VERSTR_MAX = 24;

const plural = (n: number, noun: string) => `${n} ${noun}${n === 1 ? "" : "s"}`;

/** The run a route names: its cached label, else the URL ref alone. */
export function runOf(input: CrumbInput): RunLabel {
  return input.run ?? { verstr: input.params.verstr ?? "", idx: null, name: null };
}

/** `@54 lr-sweep-3`, `@54`, or the middle-truncated verstr without an idx. */
export function runText({ verstr, idx, name }: RunLabel): string {
  if (idx == null) return midTruncate(verstr, RUN_VERSTR_MAX);
  return name ? `@${idx} ${name}` : `@${idx}`;
}

/** The code-diff page's refs, with the page's own defaults. */
export const diffRefs = (search: URLSearchParams) =>
  [search.get("v") ?? "@1", search.get("to") ?? "latest"] as const;

export const compareRefs = (search: URLSearchParams) => search.getAll("sel");

const overlayRefs = (search: URLSearchParams) =>
  (search.get("runs") ?? "").split(",").filter(Boolean);

/** The last crumb of every app route below `experiments`. */
function appLeaf(input: CrumbInput): Crumb | null {
  const { routeId, search } = input;
  if (routeId === "run") {
    const run = runOf(input);
    return { label: runText(run), mono: true, title: run.verstr, run };
  }
  if (routeId === "code-diff") {
    const [v, to] = diffRefs(search);
    return { label: `diff ${v} → ${to}` };
  }
  if (routeId === "compare-runs") return { label: `compare ${plural(compareRefs(search).length, "run")}` };
  if (routeId === "overlay") return { label: `overlay ${plural(overlayRefs(search).length, "run")}` };
  return null;
}

function appCrumbs(input: CrumbInput, base: string): Crumb[] {
  const { routeId, app = "", search } = input;
  const appCrumb: Crumb = { label: app, mono: true };
  if (routeId === "experiments") return [appCrumb, { label: "experiments" }];
  appCrumb.to = base;
  if (routeId === "actions") return [appCrumb, { label: "actions" }];
  if (routeId === "tree") {
    const v = search.get("v");
    if (!v) return [appCrumb, { label: "stamp tree" }];
    return [appCrumb, { label: "stamp tree", to: `${base}/tree` }, { label: v, mono: true }];
  }
  return [appCrumb, { label: "experiments", to: base }, appLeaf(input)!];
}

const GLOBAL: Partial<Record<RouteId, string>> = {
  home: "workspaces", apps: "apps", tokens: "API tokens", "not-found": "not found", "sign-in": "sign in",
};

const APP_ROUTES = new Set<RouteId>([
  "experiments", "run", "code-diff", "compare-runs", "overlay", "tree", "actions",
]);
export const isAppRoute = (routeId: RouteId) => APP_ROUTES.has(routeId);

export function crumbsFor(input: CrumbInput): Crumb[] {
  const { routeId, ws, appTag, params, reportTitle } = input;
  const global = GLOBAL[routeId];
  if (global) return [{ label: global }];
  if (isAppRoute(routeId)) return appCrumbs(input, `/ws/${ws}/app/${appTag}`);

  if (routeId === "models") return [{ label: "models" }];
  if (routeId === "model") {
    return [{ label: "models", to: `/ws/${ws}/models` }, { label: params.modelName ?? "", mono: true }];
  }
  if (routeId === "reports") return [{ label: "reports" }];
  const report: Crumb = { label: reportTitle || (params.rid ?? "") };
  const reports: Crumb = { label: "reports", to: `/ws/${ws}/reports` };
  if (routeId === "report") return [reports, report];
  return [reports, { ...report, to: `/ws/${ws}/reports/${params.rid}` }, { label: "edit" }];
}
