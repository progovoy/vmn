import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { textSimilar } from "../apiSimilar";
import { SimilarAnswer, SimilarCard } from "./SimilarRuns";

function TextResults({ ws, app, text, allApps }: {
  ws: string; app: string; text: string; allApps: boolean;
}) {
  const query = useQuery({
    queryKey: ["similar-text", ws, app, text, allApps],
    queryFn: () => textSimilar(ws, app, text, { allApps }),
    placeholderData: keepPreviousData,
  });
  return <SimilarAnswer error={query.error} data={query.data} app={app} />;
}

/** The leaderboard's "similar" mode, in place of its table: the runs whose
 *  intent, name, note, tags or commit subjects match the search box's text. */
export default function SimilarSearch({ ws, app, text }: { ws: string; app: string; text: string }) {
  return (
    <SimilarCard>
      {(allApps) => text ? (
        <TextResults ws={ws} app={app} text={text} allApps={allApps} />
      ) : (
        <div className="muted">Describe a run — what it changes and why — to find similar ones.</div>
      )}
    </SimilarCard>
  );
}
