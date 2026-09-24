import { useMemo, useRef } from "react";
import type { ExperimentFacets, ExperimentRow, MetricsSchema } from "../types";
import {
  anyTags, columnLayout, columnStyles, computeColMeta, metricColumns, paramKey,
} from "../pages/leaderboardColumns";
import type { RowLayout } from "../pages/LeaderboardRow";
import { sameValue } from "../util/stableRows";
import type { SuggestFacets } from "../util/querySuggest";

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

/** The table's columns: metric and param columns from the rows (minus the
 *  hidden `m:`/`p:` ones), their widths, and the row layout every row shares. */
export function useLeaderboardColumns(
  rows: readonly ExperimentRow[] | undefined,
  schema: MetricsSchema | null,
  hidden: ReadonlySet<string>,
  runBase: string,
  facets: ExperimentFacets | null,
) {
  const list = rows ?? [];
  const primary = useMemo(
    () => Object.keys(schema ?? {}).find((k) => schema![k].primary) ?? null,
    [schema],
  );
  // Keyed on the *set* of names, so a poll returning the same columns keeps
  // the same arrays (and the user's column choices).
  const [metricNames, paramNames] = useMemo(
    () => [metricColumns(rows ?? [], schema).join("\u0000"), paramKey(rows)],
    [rows, schema],
  );
  const metricCols = useMemo(() => splitKey(metricNames), [metricNames]);
  const paramCols = useMemo(() => splitKey(paramNames), [paramNames]);
  const visibleMetrics = useMemo(() => metricCols.filter((c) => !hidden.has(`m:${c}`)), [metricCols, hidden]);
  const visibleParams = useMemo(() => paramCols.filter((c) => !hidden.has(`p:${c}`)), [paramCols, hidden]);

  const colMeta = useStable(useMemo(
    () => computeColMeta(list, visibleMetrics, schema, primary),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [rows, visibleMetrics, schema, primary],
  ));
  const showBest = list.length > 1;
  const hasTags = useMemo(() => anyTags(rows), [rows]);
  const showTags = hasTags && !hidden.has(TAGS_COLUMN);

  const layout = useMemo((): RowLayout => {
    const cl = columnLayout(visibleMetrics.length, visibleParams.length, showTags);
    const paramBase = 4 + visibleMetrics.length;
    const tagsIdx = showTags ? paramBase + visibleParams.length : null;
    return {
      styles: columnStyles(cl), total: cl.total,
      metricCols: visibleMetrics, paramCols: visibleParams,
      paramBase, tagsIdx, noteIdx: paramBase + visibleParams.length + (showTags ? 1 : 0),
      colMeta, showBest, runBase,
    };
  }, [visibleMetrics, visibleParams, showTags, colMeta, showBest, runBase]);

  // Query-box suggestions: the server's app-wide keys, else what is loaded.
  const suggestFacets = useMemo((): SuggestFacets => ({
    metric_keys: facets?.metric_keys ?? metricCols,
    param_keys: facets?.param_keys ?? paramCols,
  }), [facets, metricCols, paramCols]);

  const otherCols = hasTags ? ["tags"] : [];
  const visibleOther = showTags ? ["tags"] : [];
  return {
    primary, metricCols, paramCols, visibleMetrics, visibleParams, layout, suggestFacets,
    otherCols, visibleOther,
  };
}
