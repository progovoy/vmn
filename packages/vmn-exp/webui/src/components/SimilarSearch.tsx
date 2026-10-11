import { useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { appName as toAppName } from "../api";
import { textSimilar } from "../apiSimilar";
import { ScopeSelect, SimilarList } from "./SimilarRuns";

function TextResults({ ws, app, text, allApps }: {
  ws: string; app: string; text: string; allApps: boolean;
}) {
  const query = useQuery({
    queryKey: ["similar-text", ws, app, text, allApps],
    queryFn: () => textSimilar(ws, app, text, { allApps }),
    placeholderData: keepPreviousData,
  });
  if (query.error) return <div className="error" role="alert">{(query.error as Error).message}</div>;
  if (!query.data) return <div className="muted">Looking for similar runs…</div>;
  return <SimilarList items={query.data.items} ownApp={toAppName(app)} truncated={query.data.truncated} />;
}

/** The leaderboard's "similar" mode, in place of its table: the runs whose
 *  intent, name, note, tags or commit subjects match the search box's text. */
export default function SimilarSearch({ ws, app, text }: { ws: string; app: string; text: string }) {
  const [allApps, setAllApps] = useState(false);
  return (
    <div className="card similar">
      <div className="eyebrow" style={{ display: "flex", alignItems: "center", gap: 8 }}>
        similar runs
        <ScopeSelect allApps={allApps} onChange={setAllApps} />
      </div>
      {text ? (
        <TextResults ws={ws} app={app} text={text} allApps={allApps} />
      ) : (
        <div className="muted">Describe a run — what it changes and why — to find similar ones.</div>
      )}
    </div>
  );
}
