/** The breadcrumb's root, read like a prompt: the workspace, then where its
 *  checkout stands (`main @ e71c74d`, dirty). The paths it reads from sit in
 *  the Data source popover, not in the trail. */
import { Link } from "react-router-dom";
import type { GitContext, ShellContext } from "../../shell/contracts";
import { useGitContext } from "../../shell/useShellData";
import type { Workspace } from "../../types";
import Provenance, { type Source } from "./Provenance";
import "./Topbar.css";

// The {" "} separators are dropped by the flex layout but keep copied text and
// screen-reader output readable.
function GitSegment({ git, app }: { git: GitContext; app?: string }) {
  const where = git.branch ?? (git.detached ? "detached" : "");
  return (
    <>
      {" "}
      <span className="ctx-git mono">{`${where} @ ${git.head_short ?? "(no commits)"}`}</span>
      {git.dirty && " "}
      {git.dirty && (
        <span
          className="ctx-dirty"
          title={`uncommitted changes to tracked files. vmn snapshot create ${app ?? "<app>"} saves them`}
        >
          dirty
        </span>
      )}
    </>
  );
}

function sourcesOf(workspace: Workspace | undefined, git: GitContext | undefined): Source[] {
  if (!workspace) return [];
  if (workspace.kind === "store") return workspace.store ? [{ label: "store", value: workspace.store }] : [];
  const out: Source[] = [];
  if (workspace.path) out.push({ label: "checkout", value: workspace.path });
  if (git?.store) out.push({ label: "store", value: git.store });
  return out;
}

export default function ContextRoot({ ctx }: { ctx: ShellContext }) {
  const { ws, workspace } = ctx;
  // Only a workspace known to be a checkout is asked: a store has none.
  const git = useGitContext(ws, Boolean(workspace) && ctx.isGit).data;
  if (!ws) return null;
  const isStore = workspace?.kind === "store";
  const shownGit = git && !git.error ? git : undefined;
  return (
    <span className="ctx-root">
      <Link to={`/ws/${ws}`} className="ctx-ws" title={ws}>{ws}</Link>
      {isStore ? (
        <>{" "}<span className="ctx-kind">store</span></>
      ) : (
        shownGit && <GitSegment git={shownGit} app={ctx.app} />
      )}
      {" "}
      <Provenance sources={sourcesOf(workspace, shownGit)} />
    </span>
  );
}
