/** The breadcrumb's root, read like a prompt: the workspace, then where its
 *  checkout stands (`main @ e71c74d`, dirty) and the store the UI reads. */
import { Link } from "react-router-dom";
import type { GitContext, ShellContext } from "../../shell/contracts";
import { useGitContext } from "../../shell/useShellData";
import { midTruncate } from "../../util/midTruncate";
import { wsLocation } from "../ui";
import "./Topbar.css";

const STORE_MAX = 32;

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
      {" "}
      <span className="ctx-store mono">{`· ${git.store}`}</span>
    </>
  );
}

export default function ContextRoot({ ctx }: { ctx: ShellContext }) {
  const { ws, workspace } = ctx;
  // Only a workspace known to be a checkout is asked: a store has none.
  const git = useGitContext(ws, Boolean(workspace) && ctx.isGit).data;
  if (!ws) return null;
  const store = workspace?.kind === "store" ? wsLocation(workspace) : null;
  const shownGit = git && !git.error ? git : undefined;
  // Narrow widths hide the store segment; the root's title still names it.
  const storeTitle = store ?? shownGit?.store;
  return (
    <span className="ctx-root" title={storeTitle && `store · ${storeTitle}`}>
      <Link to={`/ws/${ws}`} className="ctx-ws">{ws}</Link>
      {store !== null ? (
        <>
          {" "}
          <span className="ctx-store mono" title={store}>{`store · ${midTruncate(store, STORE_MAX)}`}</span>
        </>
      ) : (
        shownGit && <GitSegment git={shownGit} app={ctx.app} />
      )}
    </span>
  );
}
