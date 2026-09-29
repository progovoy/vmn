import { useMemo, useRef } from "react";
import type { ExperimentFacets, ExperimentRow, MetricsSchema } from "../types";
import {
  FLEET_COLS, PINNED_COLS, anyTags, columnIds, columnStyles, computeColMeta, idLayout, metricColumns,
  orderColumns, paramKey,
} from "../pages/leaderboardColumns";
import type { ColumnCell } from "../pages/leaderboardColumns";
import type { RowLayout } from "../pages/LeaderboardRow";
import { sameValue } from "../util/stableRows";
import { EMPTY_PREFS, type ColumnPrefs } from "./useColumnPrefs";
import type { SuggestFacets } from "../util/querySuggest";
import { orderedKeys } from "../util/columnOrder";
import { schemaHides } from "../util/hiddenMetrics";

/** *value*, or the previous one when structurally equal — so a poll that
 *  moves no column best leaves every memoized row alone. */
function useStable<T>(value: T): T {
  const ref = useRef(value);
  if (!sameValue(ref.current, value)) ref.current = value;
  return ref.current;
}

/** The `hide=` entry of the tags column. */
export const TAGS_COLUMN = "c:tags";

const splitKey = (key: string) => (key ? key.split("\u0000") : []);

// Stable empty array used as default param so callers that omit order/pinned
// don't trigger useMemo re-runs on every render.
const EMPTY: readonly string[] = [];

/** The table's columns: metric and param columns from the rows (minus the
 *  hidden `m:`/`p:` ones), their widths, and the row layout every row shares.
 *
 *  `order` and `pinned` come from URL params `col=` and `pin=` (as stable
 *  arrays from `useLeaderboardView`). Columns in `order` appear first;
 *  columns in `pinned` are sticky after the experiment column. */
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
  // A schema-hidden metric starts hidden, so toggling its `m:` key shows it.
  const visibleMetrics = useMemo(
    () => metricCols.filter((c) => hidden.has(`m:${c}`) === schemaHides(schema, c)),
    [metricCols, hidden, schema],
  );
  const visibleParams = useMemo(() => paramCols.filter((c) => !hidden.has(`p:${c}`)), [paramCols, hidden]);

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
    () => orderedKeys(defaultKeys, order, pinned),
    // order/pinned are stable arrays from useParamList in the view hook
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [defaultKeys, order, pinned],
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
    const pinnedSet = new Set(pinned);
    return orderedCellKeys.filter((k) => pinnedSet.has(k)).length;
  }, [orderedCellKeys, pinned]);

  const colMeta = useStable(useMemo(
    () => computeColMeta(list, visibleMetrics, schema, primary),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [rows, visibleMetrics, schema, primary],
  ));
  const showBest = list.length > 1;
  const hasTags = useMemo(() => anyTags(rows), [rows]);
  const showTags = hasTags && !hidden.has(TAGS_COLUMN);
  const visibleFleet = useMemo(() => FLEET_COLS.filter((c) => !hidden.has(`c:${c}`)), [hidden]);

  const { widths, order: savedOrder } = prefs;
  const layout = useMemo((): RowLayout => {
    // URL-pinned cells stick right after the experiment column, so they lead
    // the movable columns whatever the saved drag order says.
    const pinnedIds = orderedCellKeys.slice(0, pinnedCount);
    const moved = orderColumns(columnIds(visibleFleet, orderedCellKeys.slice(pinnedCount), showTags), savedOrder);
    const ids = [...PINNED_COLS, ...pinnedIds, ...moved.slice(PINNED_COLS.length)];
    const cl = idLayout(ids, widths, fill);
    return {
      styles: columnStyles(cl, pinnedCount), widths: cl.widths, total: cl.total, ids, cells,
      fleetCols: visibleFleet, metricCols: visibleMetrics, paramCols: visibleParams,
      tagsIdx: showTags ? ids.indexOf("c:tags") : null,
      colMeta, showBest, runBase,
    };
  }, [
    orderedCellKeys, pinnedCount, cells, visibleFleet, visibleMetrics, visibleParams, showTags,
    colMeta, showBest, runBase, widths, savedOrder, fill,
  ]);

  const suggestFacets = useMemo((): SuggestFacets => ({
    metric_keys: facets?.metric_keys ?? metricCols,
    param_keys: facets?.param_keys ?? paramCols,
  }), [facets, metricCols, paramCols]);

  const otherCols = [...FLEET_COLS, ...(hasTags ? ["tags"] : [])];
  const visibleOther = [...visibleFleet, ...(showTags ? ["tags"] : [])];
  return {
    primary, metricCols, paramCols, visibleMetrics, visibleParams, cells, defaultKeys, layout,
    suggestFacets, otherCols, visibleOther,
  };
}
