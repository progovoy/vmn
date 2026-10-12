/** `/`: the workspaces this server serves, and the form that attaches more.
 *  A first visit with one obvious destination goes straight there (§1.8). */
import { useEffect, useRef, useState } from "react";
import { Link, Navigate, useLocation, useSearchParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { useApps, useWorkspaces, WORKSPACES_KEY } from "../queries";
import { usePageScope } from "../shell/usePageScope";
import { RETURN_TO_KEY } from "../shell/contracts";
import { CopyPath, PageHead, Skeleton, wsLocation } from "../components/ui";
import AddWorkspace from "../components/AddWorkspace";
import { homeRedirect, isFirstEntry, type HomeDecision } from "./homeRedirect";
import type { Workspace } from "../types";
import "./home.css";

/** The redirect, decided once: adding a workspace later never navigates away.
 *  The first entry consumes the sign-in return path, so it is followed once. */
function useHomeRedirect(workspaces?: Workspace[]): HomeDecision {
  const location = useLocation();
  const first = isFirstEntry(location);
  const [returnTo] = useState(() => (first ? sessionStorage.getItem(RETURN_TO_KEY) : null));
  useEffect(() => {
    if (first) sessionStorage.removeItem(RETURN_TO_KEY);
  }, [first]);
  const only = workspaces?.length === 1 ? workspaces[0].name : undefined;
  const appsQuery = useApps(only);
  const apps = appsQuery.isError ? [] : appsQuery.data;
  const settled = useRef<HomeDecision>("wait");
  if (settled.current === "wait") {
    settled.current = homeRedirect({ location, returnTo, workspaces, apps });
  }
  return settled.current;
}

function WorkspaceTile({ workspace }: { workspace: Workspace }) {
  return (
    <article className="ws-tile">
      <h2><Link className="ws-tile-link" to={`/ws/${workspace.name}`}>{workspace.name}</Link></h2>
      <span className="kind-badge">{workspace.kind === "store" ? "store" : "git"}</span>
      <CopyPath text={wsLocation(workspace)} />
    </article>
  );
}

export function WorkspacesHome() {
  const { data: workspaces, error } = useWorkspaces();
  const { meta, canAdmin } = usePageScope();
  const [search] = useSearchParams();
  const client = useQueryClient();
  const decision = useHomeRedirect(error ? [] : workspaces);

  if (decision && decision !== "wait") return <Navigate replace to={decision.to} />;
  const canAttach = Boolean(meta) && canAdmin && !meta?.read_only;
  const onAdded = () => client.invalidateQueries({ queryKey: WORKSPACES_KEY });

  return (
    <>
      <PageHead title="Workspaces" mono={false} />
      <p className="page-sub">
        A workspace is a git checkout (its own working tree, .vmn/ and lock) or a store URI
        read through this server.
      </p>
      {error ? (
        <div className="error" role="alert">{String(error)}</div>
      ) : !workspaces || decision === "wait" ? (
        <Skeleton />
      ) : workspaces.length === 0 ? (
        <div className="empty">
          No workspaces yet. Start vmn-exp ui inside a vmn checkout, or attach one below.
        </div>
      ) : (
        <div className="home-grid">
          {workspaces.map((w) => <WorkspaceTile key={w.name} workspace={w} />)}
        </div>
      )}
      {canAttach && workspaces && (
        <details className="add-ws" open={search.get("add") === "1" || workspaces.length === 0}>
          <summary>Attach or clone a workspace</summary>
          <AddWorkspace onAdded={onAdded} initialName={search.get("name") ?? ""} />
        </details>
      )}
    </>
  );
}
