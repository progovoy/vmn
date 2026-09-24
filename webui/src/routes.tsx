import { lazy, Suspense, type ComponentType, type LazyExoticComponent } from "react";
import type { RouteObject } from "react-router-dom";
import App from "./App";
import { AppsPage, WorkspacesHome } from "./pages/Dashboard";
import Leaderboard from "./pages/Leaderboard";

// The landing pages ship in the main bundle; every other page loads on first
// visit, so the leaderboard never waits for chart or tree code.
const Run = lazy(() => import("./pages/Run"));
const Compare = lazy(() => import("./pages/Compare"));
const CompareRuns = lazy(() => import("./pages/CompareRuns"));
const Overlay = lazy(() => import("./pages/Overlay"));
const Snapshots = lazy(() => import("./pages/Snapshots"));
const StampTree = lazy(() => import("./pages/StampTree"));
const Actions = lazy(() => import("./pages/Actions"));

function PageFallback() {
  return <div className="route-fallback" aria-label="loading page" />;
}

const page = (Page: LazyExoticComponent<ComponentType>) => (
  <Suspense fallback={<PageFallback />}><Page /></Suspense>
);

// `handle.page` labels the breadcrumb; App reads it via useMatches so the
// route table stays the single source of truth for the URL grammar.
export const routes: RouteObject[] = [
  {
    path: "/",
    element: <App />,
    children: [
      { index: true, element: <WorkspacesHome /> },
      { path: "ws/:ws", element: <AppsPage />, handle: { page: "apps" } },
      { path: "ws/:ws/app/:app", element: <Leaderboard />, handle: { page: "experiments" } },
      { path: "ws/:ws/app/:app/run/:verstr", element: page(Run), handle: { page: "run" } },
      { path: "ws/:ws/app/:app/compare", element: page(Compare), handle: { page: "compare" } },
      { path: "ws/:ws/app/:app/compare-runs", element: page(CompareRuns), handle: { page: "compare runs" } },
      { path: "ws/:ws/app/:app/overlay", element: page(Overlay), handle: { page: "overlay" } },
      { path: "ws/:ws/app/:app/snapshots", element: page(Snapshots), handle: { page: "snapshots" } },
      { path: "ws/:ws/app/:app/tree", element: page(StampTree), handle: { page: "stamp tree" } },
      { path: "ws/:ws/app/:app/actions", element: page(Actions), handle: { page: "actions" } },
    ],
  },
];
