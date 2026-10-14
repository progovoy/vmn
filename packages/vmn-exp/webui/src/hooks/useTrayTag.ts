import { api } from "../api";
import { queryBody, type QueryGroup } from "../util/selectionGroups";
import { verstrInQuery } from "../util/selectionOverlap";
import type { TagEdit } from "../util/tags";
import { useArchiveJob } from "./useArchiveJob";
import type { useSelectionOverlap } from "./useSelectionOverlap";

type Overlap = Pick<ReturnType<typeof useSelectionOverlap>, "resolved" | "withResolved">;

/** The tray's tag edit: one `exp_tag` by query per group, plus one by
 *  `verstr in (…)` for the explicit picks no group also matches (archived
 *  ones too: they were picked by hand). *onDone* once the last succeeds. */
export function useTrayTag(ws: string, app: string, { groups, verstrs, overlap, onDone }: {
  groups: readonly QueryGroup[];
  verstrs: readonly string[];
  overlap: Overlap;
  onDone: () => void;
}) {
  const job = useArchiveJob(ws, app, onDone);
  const bodiesOf = (edit: TagEdit, dropped: ReadonlySet<string>) => {
    const picks = verstrs.filter((v) => !dropped.has(v));
    return [
      ...groups.map((g) => ({ ...queryBody(g), ...edit })),
      ...(picks.length ? [{ q: verstrInQuery(picks), archived: true, ...edit }] : []),
    ];
  };
  /** How many runs the edit changes (`dry_run` of every body). */
  const preview = (edit: TagEdit) => overlap.resolved()
    .then((dropped) => Promise.all(bodiesOf(edit, dropped).map((b) => api.actionPreview(ws, app, "exp_tag", b))))
    .then((counts) => counts.reduce((n, c) => n + c.count, 0));
  const apply = (edit: TagEdit) => overlap.withResolved((dropped) => job.run("tag", bodiesOf(edit, dropped)));
  return { preview, apply, busy: job.archiving, error: job.archiveError };
}
