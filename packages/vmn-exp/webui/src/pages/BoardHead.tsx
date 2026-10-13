import type { ReactNode } from "react";
import "./boardHead.css";

/** The board's run count: matches of a filter or a partly loaded board read
 *  "N of M runs"; the whole board counts its top-level runs, plus inner ones. */
export function runCountText({ loading, filtered, loaded, total, shownTop, loadedTop }: {
  loading: boolean; filtered: boolean;
  /** Rows loaded, of *total* matching; *shownTop* and *loadedTop* count the
   *  top-level rows on screen / loaded. */
  loaded: number; total: number; shownTop: number; loadedTop: number;
}): string {
  if (loading) return "loading runs…";
  if (filtered || loaded < total) return shownTop !== total ? `${shownTop} of ${total} runs` : `${total} runs`;
  return `${loadedTop} runs${total > loadedTop ? ` · ${total} incl. inner` : ""}`;
}

/** The leaderboard's head: the app named once, its run count beside it and
 *  the board's actions (New run, Views, Columns) on the right. */
export default function BoardHead({ title, count, actions }: {
  title: string; count: string; actions?: ReactNode;
}) {
  return (
    <div className="page-head board-head">
      <h1 className="mono">{title}</h1>
      <p className="page-sub board-count">{count}</p>
      {actions}
    </div>
  );
}
