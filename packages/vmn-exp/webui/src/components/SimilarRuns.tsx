import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { appName as toAppName } from "../api";
import { appTag } from "../http";
import { runSimilar } from "../apiSimilar";
import type { SimilarItem } from "../apiSimilar";
import type { RunState } from "../types";
import { fmtVal, relTime, runHref } from "../util";
import LazyMount from "./LazyMount";
import StatusPill from "./StatusPill";

function Intent({ intent }: { intent: NonNullable<SimilarItem["intent"]> }) {
  return (
    <details className="similar-intent">
      <summary>intent</summary>
      <div className="similar-intent-text">{intent.text}{intent.truncated && "…"}</div>
      {intent.keywords.map((k) => <span key={k} className="badge">{k}</span>)}
    </details>
  );
}

function Item({ item, ownApp }: { item: SimilarItem; ownApp: string }) {
  const label = item.name || item.verstr;
  const goal = item.goal;
  return (
    <li>
      <div className="similar-head">
        <Link className="mono" to={runHref(`/ws/${item.workspace}/app/${appTag(item.app)}`, item.verstr)}>
          {item.app === ownApp ? label : `${item.app}:${label}`}
        </Link>
        <span className="similar-score" title="similarity">{item.score.toFixed(2)}</span>
        <StatusPill status={item.status as RunState} />
        {goal && goal.value !== null && <span className="mono">{`${goal.metric}=${fmtVal(goal.value)}`}</span>}
        {item.author && <span className="muted">{item.author}</span>}
        {item.timestamp && <span className="muted">{relTime(item.timestamp)}</span>}
        {item.group_size > 1 && <span className="muted">{`(+${item.group_size - 1} runs)`}</span>}
      </div>
      {item.reasons.length > 0 && (
        <div>{item.reasons.map((r) => <span key={r} className="tag-chip">{r}</span>)}</div>
      )}
      {item.intent && <Intent intent={item.intent} />}
    </li>
  );
}

/** Similar runs, most similar first; *ownApp*'s runs are labelled without their app. */
export function SimilarList({ items, ownApp, truncated }: {
  items: SimilarItem[]; ownApp: string; truncated: boolean;
}) {
  if (items.length === 0) return <div className="muted">No similar runs</div>;
  return (
    <>
      <ul className="similar-list">
        {items.map((item) => (
          <Item key={`${item.workspace}/${item.app}/${item.verstr}`} item={item} ownApp={ownApp} />
        ))}
      </ul>
      {truncated && <div className="muted">More similar runs than shown</div>}
    </>
  );
}

/** "this app" / "all apps": where similar runs are looked for. */
export function ScopeSelect({ allApps, onChange }: { allApps: boolean; onChange: (all: boolean) => void }) {
  return (
    <select aria-label="Similar runs scope" value={allApps ? "all" : "app"}
      onChange={(e) => onChange(e.target.value === "all")} style={{ marginLeft: "auto" }}>
      <option value="app">this app</option>
      <option value="all">all apps</option>
    </select>
  );
}

function RunSimilarList({ ws, app, verstr, allApps }: {
  ws: string; app: string; verstr: string; allApps: boolean;
}) {
  const query = useQuery({
    queryKey: ["similar", ws, app, verstr, allApps],
    queryFn: () => runSimilar(ws, app, verstr, { allApps }),
  });
  if (query.error) return <div className="error">{String(query.error)}</div>;
  if (!query.data) return <div className="muted">Looking for similar runs…</div>;
  return <SimilarList items={query.data.items} ownApp={toAppName(app)} truncated={query.data.truncated} />;
}

/** The run page's "similar runs" card: fetched on its own once scrolled near,
 *  so neither the detail nor a run nobody scrolls to pays for the scoring. */
export default function SimilarRuns({ ws, app, verstr }: { ws: string; app: string; verstr: string }) {
  const [allApps, setAllApps] = useState(false);
  return (
    <div className="card similar">
      <div className="eyebrow" style={{ display: "flex", alignItems: "center", gap: 8 }}>
        similar runs
        <ScopeSelect allApps={allApps} onChange={setAllApps} />
      </div>
      <LazyMount height={40}>
        <RunSimilarList ws={ws} app={app} verstr={verstr} allApps={allApps} />
      </LazyMount>
    </div>
  );
}
