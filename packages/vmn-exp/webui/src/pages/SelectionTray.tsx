/** The app-wide selection tray: the app's picks and query groups
 *  (useRunSelection) in the selection bar. The shell mounts it once for
 *  every page of an app (SelectionTrayHost); the board on screen adds its
 *  own actions (select all matching, unarchive, a refresh once archived),
 *  elsewhere select-all has nothing more to pick and Escape leaves the
 *  selection alone. Archive and Tag are the tray's own: one bulk action by
 *  query per group (counted first with `dry_run`), then one for the explicit
 *  picks no group also matches (useSelectionOverlap: counted once). */
import { api } from "../api";
import { useArchiveJob, type ArchiveVerb } from "../hooks/useArchiveJob";
import { useRunSelection } from "../hooks/useRunSelection";
import { useSelectionOverlap } from "../hooks/useSelectionOverlap";
import { queryBody, type QueryGroup } from "../util/selectionGroups";
import LeaderboardSelectionBar from "./LeaderboardSelectionBar";
import SelectionTag from "./SelectionTag";

/** What a board adds to the tray. */
export interface BoardTray {
  total: number;
  showUnarchive: boolean;
  onSelectAll: () => void;
  /** The board's query is selected as a group: its count. */
  matching?: number | null;
  /** "Select all" selects the query itself: no cap. */
  uncapped?: boolean;
  /** After an archive succeeds (the board refreshes). */
  onArchived?: () => void;
}

const bodiesOf = (groups: readonly QueryGroup[], verstrs: readonly string[]) =>
  [...groups.map(queryBody), ...(verstrs.length ? [{ verstrs: [...verstrs] }] : [])];

export default function SelectionTray({ ws, app, board }: { ws: string; app: string; board?: BoardTray | null }) {
  const { picks, groups, clear, remove, removeGroup } = useRunSelection(ws, app);
  const job = useArchiveJob(ws, app, () => {
    clear();
    board?.onArchived?.();
  });
  const verstrs = picks.map((p) => p.verstr);
  const overlap = useSelectionOverlap(ws, app, picks, groups);
  const outside = (dropped: ReadonlySet<string>) => verstrs.filter((v) => !dropped.has(v));
  // How many runs the groups' queries now match, plus the other explicit picks.
  const preview = groups.length
    ? (verb: ArchiveVerb) => overlap.resolved().then((dropped) =>
      Promise.all(groups.map((g) => api.actionPreview(ws, app, `exp_${verb}`, queryBody(g))))
        .then((counts) => counts.reduce((n, c) => n + c.count, outside(dropped).length)))
    : undefined;
  // `total` = the picks: nothing more to select from a page without a board.
  const own = board ?? { total: picks.length, showUnarchive: false, onSelectAll: () => {} };
  return (
    <LeaderboardSelectionBar
      total={own.total} showUnarchive={own.showUnarchive} onSelectAll={own.onSelectAll}
      matching={own.matching} uncapped={own.uncapped}
      archiving={job.archiving} archiveError={job.archiveError}
      onArchive={(verb) => overlap.withResolved((dropped) => job.run(verb, bodiesOf(groups, outside(dropped))))}
      onPreview={preview} overlap={overlap.dropped.size} approximate={overlap.approximate}
      tagAction={
        <SelectionTag ws={ws} app={app} groups={groups} verstrs={verstrs} overlap={overlap} onTagged={board?.onArchived} />
      }
      selected={verstrs} picks={picks} groups={groups} base={`/ws/${ws}/app/${app}`}
      onClear={clear} onRemove={remove} onRemoveGroup={removeGroup} escClears={!!board}
    />
  );
}
