import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { apiModels } from "../apiModels";
import type { ModelKind, ModelRow } from "../apiModels";
import { relTime } from "../util";
import { PageHead, Skeleton } from "../components/ui";

const KIND_OPTIONS: [ModelKind | "", string][] = [
  ["", "all kinds"], ["model", "models"], ["dataset", "datasets"],
];

function AliasBadges({ aliases }: { aliases: Record<string, number> }) {
  const pairs = Object.entries(aliases);
  if (pairs.length === 0) return null;
  return (
    <span className="alias-badges">
      {pairs.map(([alias, n]) => (
        <span key={alias} className="badge" title={`v${n}`}>{alias}</span>
      ))}
    </span>
  );
}

function ModelTableRow({ model, ws }: { model: ModelRow; ws: string }) {
  return (
    <tr>
      <td>
        <Link to={`/ws/${ws}/models/${encodeURIComponent(model.name)}`}>{model.name}</Link>
        {" "}
        {model.kind && <span className={`badge kind-${model.kind}`}>{model.kind}</span>}
        {" "}
        <AliasBadges aliases={model.aliases} />
      </td>
      <td>{model.description ?? <span style={{ color: "var(--text-3)" }}>—</span>}</td>
      <td className="mono">{model.versions_count}</td>
      <td title={model.updated ?? ""}>{model.updated ? relTime(model.updated) : "—"}</td>
    </tr>
  );
}

function KindFilter({ kind, onChange }: { kind: string; onChange: (kind: string) => void }) {
  return (
    <select aria-label="Kind" value={kind} onChange={(e) => onChange(e.target.value)}
      style={{ marginBottom: 12 }}>
      {KIND_OPTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
    </select>
  );
}

function ModelTable({ models, ws }: { models: ModelRow[]; ws: string }) {
  if (models.length === 0) {
    return (
      <div className="card">
        <div className="empty" style={{ padding: 16 }}>
          No models registered yet.
        </div>
      </div>
    );
  }
  return (
    <div className="card" style={{ padding: 0, overflow: "auto" }}>
      <table style={{ width: "100%" }}>
        <thead>
          <tr>
            <th>name</th>
            <th>description</th>
            <th>versions</th>
            <th>updated</th>
          </tr>
        </thead>
        <tbody>
          {models.map((m) => (
            <ModelTableRow key={m.name} model={m} ws={ws} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function Models() {
  const { ws } = useParams() as { ws: string };
  const [params, setParams] = useSearchParams();
  const kind = (params.get("kind") || undefined) as ModelKind | undefined;
  const client = useQueryClient();
  const query = useQuery(
    {
      queryKey: ["models", ws, kind],
      queryFn: () => apiModels.listModels(ws, kind),
    },
    client,
  );

  const setKind = (value: string) => setParams(value ? { kind: value } : {}, { replace: true });

  return (
    <>
      <PageHead title="Models" what="model registry" mono={false} />
      <KindFilter kind={kind ?? ""} onChange={setKind} />
      {query.error && !query.data ? (
        <div className="error">{String(query.error)}</div>
      ) : query.data ? (
        <ModelTable models={query.data.models} ws={ws} />
      ) : (
        <Skeleton />
      )}
    </>
  );
}
