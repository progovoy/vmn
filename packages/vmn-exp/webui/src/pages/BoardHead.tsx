import type { ReactNode } from "react";
import { fmtCount } from "../util";
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
  if (filtered || loaded < total) {
    return shownTop !== total ? `${fmtCount(shownTop)} of ${fmtCount(total)} runs` : `${fmtCount(total)} runs`;
  }
  return `${fmtCount(loadedTop)} runs${total > loadedTop ? ` · ${fmtCount(total)} incl. inner` : ""}`;
}

/** The leaderboard's head: the app named once, its run count beside it and
 *  the board's actions (New run, Views, Columns) on the right. *live* (the
 *  phone board's freshness, whose caption is far below) shows after the
 *  count as text only: the caption keeps Pause and the live region. */
export default function BoardHead({ title, count, live, views, actions }: {
  title: string; count: string; live?: ReactNode;
  /** The experiments page's Jobs | All runs switch (plan 23 W1). */
  views?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="page-head board-head">
      <h1 className="mono">{title}</h1>
      <p className="page-sub board-count">{count}</p>
      {live && <span className="board-live" aria-hidden="true">{live}</span>}
      {views}
      {actions}
    </div>
  );
}
