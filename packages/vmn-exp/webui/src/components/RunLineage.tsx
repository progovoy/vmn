import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { appTag } from "../http";
import { runLineage } from "../apiRun";
import type { Lineage, LineageModel, LineageNode } from "../apiRun";
import type { RunState } from "../types";
import { runHref } from "../util";
import StatusPill from "./StatusPill";

const DEPTHS = [1, 2, 3];

function NodeLabel({ ws, node, ownApp }: { ws: string; node: LineageNode; ownApp: string }) {
  const label = node.name || node.verstr;
  const text = node.app === ownApp ? label : `${node.app}:${label}`;
  if (!node.found) {
    return (
      <>
        <span className="mono">{text}</span> <span className="badge">missing</span>
      </>
    );
  }
  return (
    <Link className="mono" to={runHref(`/ws/${ws}/app/${appTag(node.app)}`, node.verstr)}>
      {text}
    </Link>
  );
}

function NodeList({ ws, title, nodes, ownApp }: {
  ws: string; title: string; nodes: LineageNode[]; ownApp: string;
}) {
  if (nodes.length === 0) return null;
  return (
    <div className="lineage-group">
      <div className="k">{title}</div>
      <ul className="lineage-list">
        {nodes.map((node) => (
          <li key={`${node.app}/${node.verstr}`}>
            <NodeLabel ws={ws} node={node} ownApp={ownApp} />
            {node.status && <StatusPill status={node.status as RunState} />}
            {node.depth > 1 && <span className="muted">depth {node.depth}</span>}
            {node.links.map((l) => (
              <div key={`${l.input}/${l.artifact}/${l.via}`} className="mono muted">
                {`${l.input} ← ${l.artifact} (${l.via})`}
              </div>
            ))}
          </li>
        ))}
      </ul>
    </div>
  );
}

function ModelList({ ws, models }: { ws: string; models: LineageModel[] }) {
  if (models.length === 0) return null;
  return (
    <div className="lineage-group">
      <div className="k">models</div>
      <ul className="lineage-list">
        {models.map((m) => (
          <li key={`${m.model}/${m.version}`}>
            <Link to={`/ws/${ws}/models/${encodeURIComponent(m.model)}`}>{`${m.model} v${m.version}`}</Link>
            {m.aliases.map((a) => <span key={a} className="badge">{a}</span>)}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Upstream runs, downstream runs and registered models of one run. */
export function LineageView({ ws, lineage }: { ws: string; lineage: Lineage }) {
  const empty = !lineage.upstream.length && !lineage.downstream.length && !lineage.models.length;
  if (empty) return <div className="muted">No linked runs</div>;
  return (
    <>
      <NodeList ws={ws} title="upstream" nodes={lineage.upstream} ownApp={lineage.app} />
      <NodeList ws={ws} title="downstream" nodes={lineage.downstream} ownApp={lineage.app} />
      <ModelList ws={ws} models={lineage.models} />
      {lineage.truncated && <div className="muted">Truncated: more linked runs than shown</div>}
    </>
  );
}

/** The run page's lineage card: fetched on its own, so the detail stays fast. */
export default function RunLineage({ ws, app, verstr }: { ws: string; app: string; verstr: string }) {
  const [depth, setDepth] = useState(1);
  const query = useQuery({
    queryKey: ["lineage", ws, app, verstr, depth],
    queryFn: () => runLineage(ws, app, verstr, depth),
  });
  return (
    <div className="card lineage">
      <div className="eyebrow" style={{ display: "flex", alignItems: "center", gap: 8 }}>
        lineage
        <select aria-label="Lineage depth" value={depth}
          onChange={(e) => setDepth(Number(e.target.value))} style={{ marginLeft: "auto" }}>
          {DEPTHS.map((d) => <option key={d} value={d}>{`${d} hop${d > 1 ? "s" : ""}`}</option>)}
        </select>
      </div>
      {query.error ? (
        <div className="error">{String(query.error)}</div>
      ) : query.data ? (
        <LineageView ws={ws} lineage={query.data} />
      ) : (
        <div className="muted">Loading lineage…</div>
      )}
    </div>
  );
}
