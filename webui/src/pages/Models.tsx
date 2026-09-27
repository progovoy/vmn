import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { apiModels } from "../apiModels";
import type { ModelRow } from "../apiModels";
import { relTime } from "../util";
import { PageHead, Skeleton } from "../components/ui";

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
        <AliasBadges aliases={model.aliases} />
      </td>
      <td>{model.description ?? <span style={{ color: "var(--text-3)" }}>—</span>}</td>
      <td className="mono">{model.versions_count}</td>
      <td title={model.updated ?? ""}>{model.updated ? relTime(model.updated) : "—"}</td>
    </tr>
  );
}

export default function Models() {
  const { ws } = useParams() as { ws: string };
  const client = useQueryClient();
  const query = useQuery(
    {
      queryKey: ["models", ws],
      queryFn: () => apiModels.listModels(ws),
    },
    client,
  );

  if (query.error && !query.data) {
    return <div className="error">{String(query.error)}</div>;
  }
  if (!query.data) return <Skeleton />;

  const { models } = query.data;

  return (
    <>
      <PageHead title="Models" what="model registry" mono={false} />
      {models.length === 0 ? (
        <div className="card">
          <div className="empty" style={{ padding: 16 }}>
            No models registered yet.
          </div>
        </div>
      ) : (
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
      )}
    </>
  );
}
