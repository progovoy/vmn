import { useMemo, useRef } from "react";
import type { ExperimentFacets, ExperimentRow, MetricsSchema } from "../types";
import {
  FLEET_COLS, PINNED_COLS, anyComments, anyTags, columnIds, columnStyles, computeColMeta, defaultWidth, idLayout,
  metricColumns, orderColumns, paramKey,
} from "../pages/leaderboardColumns";
import { goalMetrics, paramBudget, variedParams } from "../pages/defaultColumns";
import type { ColumnCell } from "../pages/leaderboardColumns";
import type { RowLayout } from "../pages/LeaderboardRow";
import { sameValue } from "../util/stableRows";
import { EMPTY_PREFS, type ColumnPrefs } from "./useColumnPrefs";
import type { SuggestFacets } from "../util/querySuggest";
import { NO_PINS, orderedKeys } from "../util/columnOrder";
import { schemaHides } from "../util/hiddenMetrics";
import { GROUP_COUNT_COLS, countColumnVisible } from "../pages/groupCountColumns";

/** *value*, or the previous one when structurally equal — so a poll that
 *  moves no column best leaves every memoized row alone. */
function useStable<T>(value: T): T {
  const ref = useRef(value);
  if (!sameValue(ref.current, value)) ref.current = value;
  return ref.current;
}

/** The `show=`/`hide=` entry of the tags column; hidden by default (plan 20 D11). */
export const TAGS_COLUMN = "c:tags";

/** The `hide=` entry of the comments column; hidden by default, so listing
 *  it there shows the column. */
export const COMMENTS_COLUMN = "c:comments";

/** The note column's `show=` entry; hidden by default (plan 20 D11). */
export const NOTE_COLUMN = "c:note";

const splitKey = (key: string) => (key ? key.split("\u0000") : []);

// Stable empty array used as default param so callers that omit order/pinned
// don't trigger useMemo re-runs on every render.
const EMPTY: readonly string[] = [];
const EMPTY_SET: ReadonlySet<string> = new Set();

/** The table's columns: metric and param columns from the rows (minus the
 *  hidden `m:`/`p:` ones), their widths, and the row layout every row shares.
 *
 *  Defaults (plan 20 D11): the declared-goal metrics (every metric when no
 *  goal is declared; `show=`/`hide=` override), up to six
 *  params whose values vary across the rows (as many as fit *fill*; `show=`/
 *  `hide=` override), a grouped board's count columns (plan 22 F10; `hide=`
 *  overrides), then `when`. Note, tags and the start/end dates need `show=`.
 *
 *  `order` and `pinned` come from URL params `col=` and `pin=` (as stable
 *  arrays from `useLeaderboardView`). Columns in `order` appear first;
 *  columns in `pinned` are sticky after the experiment column. Without
 *  `pin=` the visible goal metrics are pinned; `pin=-` pins nothing. */
export function useLeaderboardColumns(
  rows: readonly ExperimentRow[] | undefined,
  schema: MetricsSchema | null,
  hidden: ReadonlySet<string>,
  runBase: string,
  facets: ExperimentFacets | null,
  order: readonly string[] = EMPTY,
  pinned: readonly string[] = EMPTY,
  /** The user's column arrangement (see useColumnPrefs). */
  prefs: ColumnPrefs = EMPTY_PREFS,
  /** Width (px) the table has to fill. */
  fill = 0,
  /** Columns the user turned on (`show=`): metrics, params, note and dates. */
  shown: ReadonlySet<string> = EMPTY_SET,
  /** A grouped board: its count columns show unless `hide=` names them (plan 22 F10). */
  grouped = false,
) {
  const list = rows ?? [];
  const primary = useMemo(
    () => Object.keys(schema ?? {}).find((k) => schema![k].primary) ?? null,
    [schema],
  );
  const [metricNames, paramNames] = useMemo(
    () => [
      metricColumns(rows ?? [], schema, facets?.metric_keys).join("\u0000"),
      paramKey(rows, facets?.param_keys),
    ],
    [rows, schema, facets],
  );
  const metricCols = useMemo(() => splitKey(metricNames), [metricNames]);
  const paramCols = useMemo(() => splitKey(paramNames), [paramNames]);
  const goals = useMemo(() => goalMetrics(metricCols, schema), [metricCols, schema]);
  // Like params: `show=` turns a metric on, `hide=` off; a non-goal metric
  // is off by default while others have a goal. A schema-hidden metric
  // keeps its older inverted key: `hide=` shows it.
  const schemaHidden = useMemo(() => metricCols.filter((c) => schemaHides(schema, c)), [metricCols, schema]);
  const visibleMetrics = useMemo(() => {
    const goal = new Set(goals);
    const legacy = new Set(schemaHidden);
    return metricCols.filter((c) => {
      const id = `m:${c}`;
      if (shown.has(id)) return true;
      if (legacy.has(c)) return hidden.has(id);
      return !hidden.has(id) && (goal.size === 0 || goal.has(c));
    });
  }, [metricCols, hidden, shown, schemaHidden, goals]);
  const varied = useStable(useMemo(
    () => variedParams(list, paramCols),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [rows, paramCols],
  ));

  const visibleFleet = useMemo(() => [
    ...GROUP_COUNT_COLS.filter((c) => countColumnVisible(`c:${c}`, hidden, grouped)),
    ...FLEET_COLS.filter((c) => shown.has(`c:${c}`)),
  ], [hidden, shown, grouped]);
  const hasTags = useMemo(() => anyTags(rows), [rows]);
  const showTags = hasTags && shown.has(TAGS_COLUMN);
  const hasComments = useMemo(() => anyComments(rows), [rows]);
  const showComments = hasComments && hidden.has(COMMENTS_COLUMN);
  const showNote = shown.has(NOTE_COLUMN);

  const { widths, order: savedOrder } = prefs;
  // Params the user turned on, then as many varying ones as fit beside
  // every other column at its width.
  const visibleParams = useMemo(() => {
    const picked = new Set(paramCols.filter((c) => shown.has(`p:${c}`)));
    const others = columnIds(
      visibleFleet, [...visibleMetrics.map((m) => `m:${m}`), ...[...picked].map((p) => `p:${p}`)],
      showTags, showComments, showNote,
    );
    const taken = others.reduce((sum, id) => sum + (widths[id] ?? defaultWidth(id)), 0);
    varied.filter((c) => !hidden.has(`p:${c}`) && !picked.has(c))
      .slice(0, paramBudget(fill, taken)).forEach((c) => picked.add(c));
    return paramCols.filter((c) => picked.has(c));
  }, [paramCols, shown, hidden, varied, visibleFleet, visibleMetrics, showTags, showComments, showNote, widths, fill]);

  // The visible goal metrics stick by default, until `pin=` says otherwise.
  const defaultPins = useMemo(
    () => goals.filter((g) => visibleMetrics.includes(g)).map((g) => `m:${g}`),
    [goals, visibleMetrics],
  );
  const pins = useMemo(
    () => (pinned.length ? pinned.filter((k) => k !== NO_PINS) : defaultPins),
    [pinned, defaultPins],
  );

  // Combined key list for ordering: m:name for metrics, p:name for params.
  const defaultKeys = useMemo(
    () => [
      ...visibleMetrics.map((m) => `m:${m}`),
      ...visibleParams.map((p) => `p:${p}`),
    ],
    [visibleMetrics, visibleParams],
  );

  // Apply URL order and pin to produce an ordered, combined cell list.
  const orderedCellKeys = useMemo(
    () => orderedKeys(defaultKeys, order, pins),
    // order/pinned are stable arrays from useParamList in the view hook
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [defaultKeys, order, pins],
  );

  const cells = useMemo(
    (): readonly ColumnCell[] =>
      orderedCellKeys.map((k) => ({
        kind: (k.startsWith("m:") ? "metric" : "param") as ColumnCell["kind"],
        key: k.slice(2),
      })),
    [orderedCellKeys],
  );

  const pinnedCount = useMemo(() => {
    const pinnedSet = new Set(pins);
    return orderedCellKeys.filter((k) => pinnedSet.has(k)).length;
  }, [orderedCellKeys, pins]);

  const colMeta = useStable(useMemo(
    () => computeColMeta(list, visibleMetrics, schema, primary),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [rows, visibleMetrics, schema, primary],
  ));
  const showBest = list.length > 1;
  const layout = useMemo((): RowLayout => {
    // URL-pinned cells stick right after the experiment column, so they lead
    // the movable columns whatever the saved drag order says.
    const pinnedIds = orderedCellKeys.slice(0, pinnedCount);
    const movable = columnIds(visibleFleet, orderedCellKeys.slice(pinnedCount), showTags, showComments, showNote);
    const moved = orderColumns(movable, savedOrder);
    const ids = [...PINNED_COLS, ...pinnedIds, ...moved.slice(PINNED_COLS.length)];
    const cl = idLayout(ids, widths, fill);
    return {
      styles: columnStyles(cl, pinnedCount), widths: cl.widths, total: cl.total, ids, cells,
      fleetCols: visibleFleet, metricCols: visibleMetrics, paramCols: visibleParams,
      tagsIdx: showTags ? ids.indexOf("c:tags") : null,
      colMeta, showBest, runBase,
    };
  }, [
    orderedCellKeys, pinnedCount, cells, visibleFleet, visibleMetrics, visibleParams, showTags, showComments, showNote,
    colMeta, showBest, runBase, widths, savedOrder, fill,
  ]);

  const suggestFacets = useMemo((): SuggestFacets => ({
    metric_keys: facets?.metric_keys ?? metricCols,
    param_keys: facets?.param_keys ?? paramCols,
  }), [facets, metricCols, paramCols]);

  const otherCols = [...(grouped ? GROUP_COUNT_COLS : []), ...FLEET_COLS, "note", ...(hasTags ? ["tags"] : []), ...(hasComments ? ["comments"] : [])];
  const visibleOther = [
    ...visibleFleet, ...(showNote ? ["note"] : []), ...(showTags ? ["tags"] : []), ...(showComments ? ["comments"] : []),
  ];
  return {
    primary, metricCols, paramCols, schemaHidden, visibleMetrics, visibleParams, cells, defaultKeys, layout, pinned: pins, defaultPins,
    suggestFacets, otherCols, visibleOther,
  };
}
