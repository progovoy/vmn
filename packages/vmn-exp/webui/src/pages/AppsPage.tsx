/** `/ws/:ws`: the workspace's apps, each with its run count and what needs
 *  attention now (§1.8, §1.9). */
import { Link, useParams } from "react-router-dom";
import { appTag } from "../api";
import { useApps } from "../queries";
import { usePageScope } from "../shell/usePageScope";
import { useAppStatus } from "../shell/useShellData";
import { PageHead, Skeleton, wsLocation } from "../components/ui";
import CacheResync, { useCacheStatus } from "../components/CacheResync";
import LazyMount from "../components/LazyMount";
import StatusRollup from "../components/shell/StatusRollup";
import type { AppRow, Workspace } from "../types";
import "./home.css";

const count = (n: number, noun: string) => `${n} ${noun}${n === 1 ? "" : "s"}`;

function TileStatus({ ws, tag }: { ws: string; tag: string }) {
  const { data } = useAppStatus(ws, tag);
  return <StatusRollup status={data} href={(search) => `/ws/${ws}/app/${tag}${search}`} />;
}

function AppTile({ ws, app, isGit }: { ws: string; app: AppRow; isGit: boolean }) {
  const tag = appTag(app.name);
  const runs = count(app.experiments, "run");
  return (
    <article className="app-tile">
      <h2><Link className="app-tile-link" to={`/ws/${ws}/app/${tag}`}>{app.name}</Link></h2>
      <span className="app-tile-meta">{isGit ? `${runs} · ${count(app.versions, "version")}` : runs}</span>
      <LazyMount height={18}><TileStatus ws={ws} tag={tag} /></LazyMount>
    </article>
  );
}

function subLine(apps: AppRow[], workspace?: Workspace): string {
  const head = count(apps.length, "app");
  if (!workspace) return head;
  return `${head} · ${workspace.kind === "store" ? "store" : "git"} · ${wsLocation(workspace)}`;
}

function EmptyApps({ ws, isGit }: { ws: string; isGit: boolean }) {
  if (!isGit) return <div className="empty">No runs in this store yet.</div>;
  return (
    <div className="empty">
      No vmn apps in {ws} yet. Run <code>vmn stamp -r patch &lt;app&gt;</code> or{" "}
      <code>vmn-exp run &lt;app&gt; -- &lt;cmd&gt;</code> in the checkout.
    </div>
  );
}

/** Off the solo path: a configured server's cache controls, for admins only. */
function ServerCache({ ws }: { ws: string }) {
  const { data } = useCacheStatus(ws);
  if (!data) return null;
  return (
    <details className="cache-details">
      <summary>Server cache</summary>
      <CacheResync ws={ws} />
    </details>
  );
}

export function AppsPage() {
  const { ws } = useParams() as { ws: string };
  const { data: apps, error } = useApps(ws);
  const { workspace, isGit, meta } = usePageScope(ws);

  return (
    <>
      <PageHead title={ws} mono={false} />
      {error ? (
        <div className="error" role="alert">{String(error)}</div>
      ) : !apps ? (
        <Skeleton />
      ) : (
        <>
          <p className="page-sub">{subLine(apps, workspace)}</p>
          {apps.length === 0 ? (
            <EmptyApps ws={ws} isGit={isGit} />
          ) : (
            <div className="home-grid">
              {apps.map((a) => <AppTile key={a.name} ws={ws} app={a} isGit={isGit} />)}
            </div>
          )}
        </>
      )}
      {meta?.mode === "configured" && <ServerCache ws={ws} />}
    </>
  );
}
