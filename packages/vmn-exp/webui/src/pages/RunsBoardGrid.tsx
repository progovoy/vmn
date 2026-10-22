/** A runs board's table, its caption (sort, freshness, density) and the
 *  Load more button: the same in the All runs view and a job's Runs tab. */
import type { RunsBoard } from "../hooks/useRunsBoard";
import type { useLeaderboardView } from "../hooks/useLeaderboardView";
import BoardCaption, { BOARD_CAPTION_ID } from "./BoardCaption";
import BoardGridTools from "./BoardGridTools";
import LeaderboardTable from "./LeaderboardTable";
import NewRowsBar from "../components/NewRowsBar";
import StaleRows from "../components/StaleRows";

export default function RunsBoardGrid({ board, view, flash = null, paused, onPaused }: {
  board: RunsBoard;
  view: ReturnType<typeof useLeaderboardView>;
  /** A run to highlight (just created). */
  flash?: string | null;
  paused: boolean;
  onPaused: (paused: boolean) => void;
}) {
  const { data, selection, sortState } = board;
  return (
    <StaleRows stale={data.stale} error={data.staleError}>
      <NewRowsBar pending={data.pending} onShow={data.showNew} />
      <LeaderboardTable
        rows={board.tableItems}
        layout={board.layout}
        sort={sortState}
        selected={view.selected}
        flash={flash}
        onToggle={selection.toggle}
        headerCheck={{ state: selection.headerCheck, onToggle: selection.toggleAll }}
        onPrefetch={board.onPrefetch}
        groups={board.groupActions}
        hasMore={data.hasMore}
        onNearEnd={data.loadMore}
        visibleRef={data.visibleRef}
        viewportRef={data.viewportRef}
        edits={board.columnEdits}
        onFit={board.setTableWidth}
        describedBy={BOARD_CAPTION_ID}
        density={view.density}
        onClearAnchor={selection.clearAnchor}
      />
      <BoardCaption
        sortLabel={board.sortLabel} reversed={sortState.reversed}
        live={{ running: board.anyRunning, paused, updatedAt: data.updatedAt, onPaused, onRefresh: board.refresh }}
        tools={<BoardGridTools density={view.density} onDensity={view.setDensity} />}
      />
      {board.rows !== undefined && data.hasMore && (
        <div className="load-more">
          <button onClick={data.loadMore}>{data.moreLabel}</button>
          {data.moreError && <span className="error">{data.moreError}</span>}
        </div>
      )}
    </StaleRows>
  );
}
