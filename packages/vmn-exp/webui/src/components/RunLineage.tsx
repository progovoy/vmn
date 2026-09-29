import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { appTag } from "../http";
import { runLineage } from "../apiRun";
import type { Lineage, LineageDataset, LineageLink, LineageModel, LineageNode } from "../apiRun";
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

function modelHref(ws: string, model: string) {
  return `/ws/${ws}/models/${encodeURIComponent(model)}`;
}

function LinkLine({ ws, link }: { ws: string; link: LineageLink }) {
  return (
    <div className="mono muted">
      {`${link.input} ← ${link.artifact} (${link.via})`}
      {link.model && (
        <Link className="badge" to={modelHref(ws, link.model)}>
          {`${link.kind} ${link.model} v${link.version}`}
        </Link>
      )}
    </div>
  );
}

/** A titled list of lineage run nodes; *ownApp*'s runs are labelled without their app. */
export function NodeList({ ws, title, nodes, ownApp }: {
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
              <LinkLine key={`${l.input}/${l.artifact}/${l.via}`} ws={ws} link={l} />
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
            <Link to={modelHref(ws, m.model)}>{`${m.model} v${m.version}`}</Link>
            {m.aliases.map((a) => <span key={a} className="badge">{a}</span>)}
          </li>
        ))}
      </ul>
    </div>
  );
}

function DatasetList({ ws, datasets }: { ws: string; datasets: LineageDataset[] }) {
  if (datasets.length === 0) return null;
  return (
    <div className="lineage-group">
      <div className="k">datasets</div>
      <ul className="lineage-list">
        {datasets.map((d) => {
          const label = `${d.model} v${d.version}`;
          return (
            <li key={d.input}>
              {d.found === false ? (
                <><span className="mono">{label}</span> <span className="badge">missing</span></>
              ) : (
                <Link className="mono" to={modelHref(ws, d.model)}>{label}</Link>
              )}
              {d.digest && <span className="mono muted">{d.digest}</span>}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/** Upstream runs, downstream runs, used datasets and registered models of one run. */
export function LineageView({ ws, lineage }: { ws: string; lineage: Lineage }) {
  const datasets = lineage.datasets ?? [];
  const empty = !lineage.upstream.length && !lineage.downstream.length &&
    !lineage.models.length && !datasets.length;
  if (empty) return <div className="muted">No linked runs</div>;
  return (
    <>
      <NodeList ws={ws} title="upstream" nodes={lineage.upstream} ownApp={lineage.app} />
      <NodeList ws={ws} title="downstream" nodes={lineage.downstream} ownApp={lineage.app} />
      <DatasetList ws={ws} datasets={datasets} />
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
