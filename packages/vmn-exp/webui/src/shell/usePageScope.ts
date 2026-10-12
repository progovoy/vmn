/** What a page may know about where it is and what it may do: meta and the
 *  workspaces only (no router matches), so it works under a plain MemoryRouter. */
import { useMeta, useWorkspaces } from "../queries";
import type { HttpError } from "../http";
import type { Meta, Role, Workspace } from "../types";
import type { PageScope } from "./contracts";

type MetaStatus = PageScope["metaStatus"];

function metaStatusOf(isError: boolean, error: unknown, data: Meta | undefined): MetaStatus {
  if (isError) {
    const status = (error as HttpError | null)?.status;
    if (status === 401) return "unauthorized";
    if (status === 403) return "forbidden";
    return "unreachable";
  }
  return data ? "ok" : "loading";
}

/** The first read-only reason that applies (plan 19 §2.2), else null. */
function readOnlyReasonOf(
  meta: Meta | undefined, authEnabled: boolean, role: Role | null,
  ws: string | undefined, workspace: Workspace | undefined,
): string | null {
  if (meta?.read_only) return "Started with --read-only: actions and edits are off";
  if (authEnabled && role === "viewer") return ws ? `Your role in ${ws} is viewer` : "Your role is viewer";
  if (authEnabled && ws && workspace && role === null) return `You have no role in ${ws}`;
  // Capabilities not probed yet are unknown: the server still refuses what it can't do.
  if (workspace?.kind === "store" && workspace.capabilities && !workspace.capabilities.includes("edit")) {
    return "This store gives no edit access";
  }
  return null;
}

export function usePageScope(ws?: string): PageScope {
  const metaQuery = useMeta();
  const workspaces = useWorkspaces().data ?? [];
  const meta = metaQuery.data;
  const workspace = ws ? workspaces.find((w) => w.name === ws) : undefined;
  const authEnabled = meta?.auth?.enabled ?? false;
  const role = workspace?.role ?? meta?.role ?? null;
  const metaStatus = metaStatusOf(metaQuery.isError, metaQuery.error, meta);
  const readOnlyReason = readOnlyReasonOf(meta, authEnabled, role, ws, workspace);
  const canAdmin = !authEnabled || meta?.role === "admin";
  return {
    ws, workspace, workspaces,
    isGit: workspace?.kind !== "store",
    meta, metaStatus,
    authEnabled, role,
    readOnly: readOnlyReason !== null,
    readOnlyReason,
    canAdmin,
    canAttach: metaStatus === "ok" && !meta?.read_only && canAdmin,
  };
}
