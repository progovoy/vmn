import { lazy, Suspense, type ComponentType, type LazyExoticComponent, type ReactNode } from "react";
import type { RouteObject } from "react-router-dom";
import App from "./App";
import { RouteNotFound } from "./components/shell/NotFound";
import PageFallback from "./components/shell/PageFallback";
import RouteError from "./components/shell/RouteError";
import { AppGuard, GitOnly, WorkspaceGuard } from "./components/shell/guards";
import { AppsPage } from "./pages/AppsPage";
import { WorkspacesHome } from "./pages/WorkspacesHome";
import Leaderboard from "./pages/Leaderboard";
import { LegacyCompareRedirect } from "./pages/Compare/legacyRedirects";
import type { RouteHandle, RouteId } from "./shell/contracts";

// The landing pages ship in the main bundle; every other page loads on first
// visit, so the leaderboard never waits for chart or tree code.
const Run = lazy(() => import("./pages/Run"));
const ComparePage = lazy(() => import("./pages/Compare/ComparePage"));
const StampTree = lazy(() => import("./pages/StampTree"));
const Actions = lazy(() => import("./pages/Actions"));
const Models = lazy(() => import("./pages/Models"));
const ModelDetail = lazy(() => import("./pages/ModelDetail"));
const Tokens = lazy(() => import("./pages/Tokens"));
const Reports = lazy(() => import("./pages/Reports"));
const Report = lazy(() => import("./pages/Report"));
const ReportEdit = lazy(() => import("./pages/ReportEdit"));

const page = (Page: LazyExoticComponent<ComponentType>, label: string) => (
  <Suspense fallback={<PageFallback label={label} />}><Page /></Suspense>
);

// The guards wrap elements, not layout routes: the children stay flat and a
// page keeps its mount across param changes.
const inWs = (el: ReactNode) => <WorkspaceGuard>{el}</WorkspaceGuard>;
const inApp = (el: ReactNode) => inWs(<AppGuard>{el}</AppGuard>);
const inGitApp = (p: "tree" | "actions", el: ReactNode) => inApp(<GitOnly page={p}>{el}</GitOnly>);

/** A child route: `handle.id` drives the shell's crumbs, title and nav. A
 *  child's error renders in the shell's outlet, so the frame survives it. */
function child(path: string | undefined, id: RouteId, element: ReactNode, wide?: boolean): RouteObject {
  const handle: RouteHandle = wide ? { id, wide } : { id };
  const base = { element, handle, errorElement: <RouteError /> };
  return path === undefined ? { index: true, ...base } : { path, ...base };
}

export const routes: RouteObject[] = [
  {
    path: "/",
    element: <App />,
    children: [
      child(undefined, "home", <WorkspacesHome />),
      child("tokens", "tokens", page(Tokens, "API tokens")),
      child("ws/:ws", "apps", inWs(<AppsPage />)),
      child("ws/:ws/app/:app", "experiments", inApp(<Leaderboard />), true),
      child("ws/:ws/app/:app/run/:verstr", "run", inApp(page(Run, "run"))),
      child("ws/:ws/app/:app/compare-runs", "compare-runs", inApp(page(ComparePage, "comparison"))),
      // The pages Compare replaced (D6): old links land on its code / curves tab.
      child("ws/:ws/app/:app/compare", "code-diff", <LegacyCompareRedirect from="code" />),
      child("ws/:ws/app/:app/overlay", "overlay", <LegacyCompareRedirect from="overlay" />),
      child("ws/:ws/app/:app/tree", "tree", inGitApp("tree", page(StampTree, "stamp tree"))),
      child("ws/:ws/app/:app/actions", "actions", inGitApp("actions", page(Actions, "actions"))),
      child("ws/:ws/models", "models", inWs(page(Models, "models"))),
      child("ws/:ws/models/:modelName", "model", inWs(page(ModelDetail, "model"))),
      child("ws/:ws/reports", "reports", inWs(page(Reports, "reports"))),
      child("ws/:ws/reports/:rid", "report", inWs(page(Report, "report"))),
      child("ws/:ws/reports/:rid/edit", "report-edit", inWs(page(ReportEdit, "report editor"))),
      child("*", "not-found", <RouteNotFound />),
    ],
  },
];
