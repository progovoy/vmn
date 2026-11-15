import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { api, appName as toAppName } from "../api";
import type { VersionRow } from "../types";
import { PageHead, Skeleton } from "../components/ui";
import { layout, type Node } from "./StampTree/layout";
import { isNotARepoError, NotARepoMessage, type NotARepoError } from "./StampTree/NotARepo";
import { TreeGraph } from "./StampTree/TreeGraph";
import { TreeSidePanel } from "./StampTree/TreeSidePanel";

function RootVersions({ roots }: { roots: VersionRow[] }) {
  return (
    <div className="card">
      <h2 style={{ marginTop: 0 }}>root versions → services</h2>
      {roots
        .slice()
        .sort((a, b) => (b.timestamp ?? 0) - (a.timestamp ?? 0))
        .map((r) => (
          <div key={r.tag} style={{ marginBottom: 10 }}>
            <span className="badge">root {r.verstr}</span>{" "}
            {Object.entries(r.services ?? {}).map(([s, ver]) => (
              <span key={s} className="mono" style={{ marginRight: 12 }}>
                {s}@{ver}
              </span>
            ))}
          </div>
        ))}
    </div>
  );
}

export default function StampTree() {
  const { ws, app } = useParams() as { ws: string; app: string };
  const [rows, setRows] = useState<VersionRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [repoError, setRepoError] = useState<NotARepoError | null>(null);
  const [params, setParams] = useSearchParams();
  const selected = params.get("v");

  useEffect(() => {
    api.versions(ws, app).then(setRows).catch((e) => {
      if (isNotARepoError(e)) {
        setRepoError(e.body as NotARepoError);
      } else {
        setError(String(e));
      }
    });
  }, [ws, app]);

  const versions = useMemo(
    () => (rows ?? []).filter((r) => r.kind === "version"),
    [rows]
  );
  const roots = useMemo(
    () => (rows ?? []).filter((r) => r.kind === "root"),
    [rows]
  );
  const { nodes, edges, canonical, textX, labelEnd, presentModes } = useMemo(
    () => layout(versions),
    [versions]
  );
  const byVerstr = useMemo<Record<string, Node>>(
    () => Object.fromEntries(nodes.map((n) => [n.verstr, n])),
    [nodes]
  );
  const select = useCallback(
    (verstr: string) => setParams({ v: verstr }, { replace: true }),
    [setParams]
  );
  const current =
    (selected && byVerstr[canonical.get(selected) ?? selected]) || nodes[0];
  // Versions older than the selected one (nodes are newest-first) — the
  // candidates for the changelog "from" dropdown.
  const olderVerstrs = useMemo(() => {
    const i = current ? nodes.findIndex((n) => n.verstr === current.verstr) : -1;
    return i < 0 ? [] : nodes.slice(i + 1).map((n) => n.verstr);
  }, [nodes, current]);

  if (repoError) {
    return (
      <>
        <PageHead title={toAppName(app)} what="stamp tree" />
        <NotARepoMessage path={repoError.path} />
      </>
    );
  }
  if (error) return <div className="error">{error}</div>;
  if (rows === null) return <Skeleton />;

  return (
    <>
      <PageHead title={toAppName(app)} what="stamp tree" />
      <p className="page-sub">
        version history as a DAG · node color = release mode · lane = branch
      </p>

      {nodes.length === 0 && roots.length === 0 && (
        <div className="empty">No stamped versions yet.</div>
      )}

      {nodes.length > 0 && (
        <div style={{ display: "flex", gap: 16, alignItems: "flex-start", flexWrap: "wrap" }}>
          <TreeGraph
            nodes={nodes} edges={edges} byVerstr={byVerstr} current={current}
            textX={textX} labelEnd={labelEnd} onSelect={select}
          />
          <TreeSidePanel
            ws={ws} app={app} current={current} canonical={canonical} edges={edges}
            olderVerstrs={olderVerstrs} presentModes={presentModes} onSelect={select}
          />
        </div>
      )}

      {roots.length > 0 && <RootVersions roots={roots} />}
    </>
  );
}
