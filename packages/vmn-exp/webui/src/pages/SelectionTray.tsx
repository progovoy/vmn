/** The app-wide selection tray: the app's picks (useRunSelection) in the
 *  selection bar, on every page of the app. A board passes its own
 *  actions (select all matching, archive by query, unarchive); elsewhere
 *  the tray archives the picks itself and Escape leaves them alone. */
import { useArchiveJob } from "../hooks/useArchiveJob";
import { useRunSelection } from "../hooks/useRunSelection";
import LeaderboardSelectionBar from "./LeaderboardSelectionBar";

type BarProps = Parameters<typeof LeaderboardSelectionBar>[0];
/** What a board adds to the tray. */
export type BoardTray = Pick<BarProps, "total" | "showUnarchive" | "archiving" | "archiveError" | "onSelectAll"
  | "onArchive" | "matching" | "onPreview" | "uncapped">;

export default function SelectionTray({ ws, app, board }: { ws: string; app: string; board?: BoardTray }) {
  const { picks, clear, remove } = useRunSelection(ws, app);
  const job = useArchiveJob(ws, app, clear);
  // `total` = the picks: nothing more to select from a page without a board.
  const own: BoardTray = {
    total: picks.length, showUnarchive: false, onSelectAll: () => {},
    onArchive: (verb) => job.run(verb, { verstrs: picks.map((p) => p.verstr) }),
    archiving: job.archiving, archiveError: job.archiveError,
  };
  return (
    <LeaderboardSelectionBar
      {...(board ?? own)}
      selected={picks.map((p) => p.verstr)} picks={picks} base={`/ws/${ws}/app/${app}`}
      onClear={clear} onRemove={remove} escClears={!!board}
    />
  );
}
