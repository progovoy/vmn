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
import Tree from "./pages/Tree";
import "./styles.css";

const router = createBrowserRouter([
  {
    path: "/",
    element: <App />,
    children: [
      { index: true, element: <WorkspacesHome /> },
      { path: "ws/:ws", element: <AppsPage /> },
      { path: "ws/:ws/app/:app", element: <Leaderboard /> },
      { path: "ws/:ws/app/:app/run/:verstr", element: <Run /> },
      { path: "ws/:ws/app/:app/compare", element: <Compare /> },
      { path: "ws/:ws/app/:app/snapshots", element: <Snapshots /> },
      { path: "ws/:ws/app/:app/tree", element: <Tree /> },
      { path: "ws/:ws/app/:app/actions", element: <Actions /> },
    ],
  },
]);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <RouterProvider router={router} />
  </React.StrictMode>
);
