import { useEffect, useState } from "react";
import {
  Link, NavLink, Outlet, useNavigate, useParams,
} from "react-router-dom";
import { api } from "./api";
import type { Workspace } from "./types";

export default function App() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const { ws } = useParams();
  const navigate = useNavigate();

  useEffect(() => {
    api.workspaces().then(setWorkspaces).catch(() => setWorkspaces([]));
  }, []);

  return (
    <div className="layout">
      <header className="header">
        <Link to="/" className="brand">
          vmn<span> ui</span>
        </Link>
        <select
          value={ws ?? ""}
          onChange={(e) => e.target.value && navigate(`/ws/${e.target.value}`)}
        >
          <option value="" disabled>
            workspace…
          </option>
          {workspaces.map((w) => (
            <option key={w.name} value={w.name}>
              {w.name} {w.kind === "s3" ? "(s3)" : ""}
            </option>
          ))}
        </select>
        {ws && (
          <nav>
            <NavLink to={`/ws/${ws}`} end>
              apps
            </NavLink>
          </nav>
        )}
      </header>
      <main className="main">
        <Outlet />
      </main>
    </div>
  );
}
