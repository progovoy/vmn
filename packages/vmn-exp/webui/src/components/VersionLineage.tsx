import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiModels } from "../apiModels";
import type { VersionLineage } from "../apiModels";
import { NodeList } from "./RunLineage";

function LineageBody({ ws, lineage }: { ws: string; lineage: VersionLineage }) {
  return (
    <>
      <NodeList ws={ws} title="produced by"
        nodes={lineage.producer ? [lineage.producer] : []} ownApp="" />
      <NodeList ws={ws} title="used by" nodes={lineage.consumers} ownApp="" />
      {lineage.consumers.length === 0 && <div className="muted">No recorded use</div>}
    </>
  );
}

/** A model page's lineage card: the run a version came from and the runs
 *  recorded using it, for one picked version (the newest by default). */
export default function VersionLineagePanel({ ws, model, versions }: {
  ws: string; model: string; versions: number[];
}) {
  const [picked, setPicked] = useState<number | null>(null);
  const version = picked ?? Math.max(...versions);
  const query = useQuery({
    queryKey: ["version-lineage", ws, model, version],
    queryFn: () => apiModels.versionLineage(ws, model, version),
  });
  return (
    <div className="card lineage" style={{ marginBottom: 16 }}>
      <div className="eyebrow" style={{ display: "flex", alignItems: "center", gap: 8 }}>
        lineage
        <select aria-label="Lineage version" value={version}
          onChange={(e) => setPicked(Number(e.target.value))} style={{ marginLeft: "auto" }}>
          {versions.map((n) => <option key={n} value={n}>{`version ${n}`}</option>)}
        </select>
      </div>
      {query.error ? (
        <div className="error">{String(query.error)}</div>
      ) : query.data ? (
        <LineageBody ws={ws} lineage={query.data} />
      ) : (
        <div className="muted">Loading lineage…</div>
      )}
    </div>
  );
}
