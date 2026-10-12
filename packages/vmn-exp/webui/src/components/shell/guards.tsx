/** Route element wrappers that swap a page for its not-found once the data
 *  says the workspace or app is missing. They keep routes flat (a page keeps
 *  its mount across param changes) and read params, never router matches. */
import type { ReactNode } from "react";
import { useParams } from "react-router-dom";
import { useWorkspaces } from "../../queries";
import { useAppExists } from "../../shell/useAppExists";
import { usePageScope } from "../../shell/usePageScope";
import NotFound from "./NotFound";

/** Renders *children* until the loaded workspace list lacks `:ws`. */
export function WorkspaceGuard({ children }: { children: ReactNode }) {
  const { ws } = useParams();
  const list = useWorkspaces().data;
  if (ws && list && !list.some((w) => w.name === ws)) return <NotFound kind="workspace" ws={ws} />;
  return <>{children}</>;
}

/** Renders *children* at once; swaps to the not-found once the server says `:app` is missing. */
export function AppGuard({ children }: { children: ReactNode }) {
  const { ws, app } = useParams();
  const exists = useAppExists(ws, app);
  if (ws && app && exists === false) return <NotFound kind="app" ws={ws} appTag={app} />;
  return <>{children}</>;
}

/** The stamp tree and actions read git: a store workspace has neither. */
export function GitOnly({ page, children }: { page: "tree" | "actions"; children: ReactNode }) {
  const { ws, app } = useParams();
  const { workspace } = usePageScope(ws);
  if (ws && app && workspace?.kind === "store") {
    return <NotFound kind="needs-git" ws={ws} appTag={app} page={page} />;
  }
  return <>{children}</>;
}
