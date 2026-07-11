import React from "react";
import ReactDOM from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import App from "./App";
import Actions from "./pages/Actions";
import { AppsPage, WorkspacesHome } from "./pages/Dashboard";
import Compare from "./pages/Compare";
import Leaderboard from "./pages/Leaderboard";
import Run from "./pages/Run";
import Snapshots from "./pages/Snapshots";
import StampTree from "./pages/StampTree";
import "./styles.css";

// `handle.page` labels the breadcrumb; App reads it via useMatches so the
// route table stays the single source of truth for the URL grammar.
const router = createBrowserRouter([
  {
    path: "/",
    element: <App />,
    children: [
      { index: true, element: <WorkspacesHome /> },
      { path: "ws/:ws", element: <AppsPage />, handle: { page: "apps" } },
      { path: "ws/:ws/app/:app", element: <Leaderboard />, handle: { page: "experiments" } },
      { path: "ws/:ws/app/:app/run/:verstr", element: <Run />, handle: { page: "run" } },
      { path: "ws/:ws/app/:app/compare", element: <Compare />, handle: { page: "compare" } },
      { path: "ws/:ws/app/:app/snapshots", element: <Snapshots />, handle: { page: "snapshots" } },
      { path: "ws/:ws/app/:app/tree", element: <StampTree />, handle: { page: "stamp tree" } },
      { path: "ws/:ws/app/:app/actions", element: <Actions />, handle: { page: "actions" } },
    ],
  },
]);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <RouterProvider router={router} />
  </React.StrictMode>
);
