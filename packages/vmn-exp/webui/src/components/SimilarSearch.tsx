import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { textSimilar } from "../apiSimilar";
import { SimilarAnswer, SimilarCard } from "./SimilarRuns";

/** What narrows the candidates: the leaderboard's filters, as the text route takes them. */
export interface SimilarFilter {
  /** The query-language query (typed query, branch, statuses), or undefined. */
  query?: string;
  /** Let archived runs be candidates; undefined for no. */
  archived?: boolean;
}

function TextResults({ ws, app, text, allApps, filter }: {
  ws: string; app: string; text: string; allApps: boolean; filter: SimilarFilter;
}) {
  const query = useQuery({
    queryKey: ["similar-text", ws, app, text, allApps, filter.query, filter.archived],
    queryFn: () => textSimilar(ws, app, text, { allApps, ...filter }),
    placeholderData: keepPreviousData,
  });
  return <SimilarAnswer error={query.error} data={query.data} app={app} />;
}

/** The leaderboard's "similar" mode, in place of its table: the runs whose
 *  intent, name, note, tags or commit subjects match the search box's text,
 *  among those the board's filters keep. */
export default function SimilarSearch({ ws, app, text, filter = {} }: {
  ws: string; app: string; text: string; filter?: SimilarFilter;
}) {
  return (
    <SimilarCard>
      {(allApps) => text ? (
        <TextResults ws={ws} app={app} text={text} allApps={allApps} filter={filter} />
      ) : (
        <div className="muted">Describe a run — what it changes and why — to find similar ones.</div>
      )}
    </SimilarCard>
  );
}
