// Types for `vmn-panel` report blocks. The canonical validator is
// vmn_exp/core/panel_spec.py; panelSpec.schema.json is generated from it.
// validate() mirrors only the required fields so a panel can show an error box.

export type PinnedRuns = { verstrs: string[] };
export type QueryRuns = {
  query: string;
  sort?: string;
  order?: "asc" | "desc";
  limit?: number;
  archived?: boolean;
};

type Common<T extends string, R = PinnedRuns | QueryRuns> = {
  v: 1;
  id: string;
  type: T;
  app: string;
  runs: R;
  title?: string;
  height?: number;
};

export type XAxis = {
  mode: "step" | "wall" | "relative" | "metric";
  metric?: string;
};

export type PanelSpec =
  | (Common<"curves"> & {
      keys: string[];
      x?: XAxis;
      smoothing?: number;
      log_y?: boolean;
      max_points?: number;
    })
  | (Common<"leaderboard"> & { columns?: string[]; params?: string[] })
  | (Common<"bar"> & { metric: string })
  | (Common<"scatter"> & { x: string; y: string })
  | (Common<"parallel"> & { columns: string[] })
  | (Common<"importance"> & { metric: string })
  | (Common<"grouped"> & { group_by: string; metric: string })
  | (Common<"media", PinnedRuns> & { key: string; step?: number | "last" })
  | (Common<"table", PinnedRuns> & { path: string })
  | (Common<"histogram", PinnedRuns> & { key: string })
  | (Common<"lineage", PinnedRuns> & { depth?: number })
  | Common<"run", PinnedRuns>;

export type PanelType = PanelSpec["type"];

const TYPE_REQUIRED: Record<PanelType, string[]> = {
  curves: ["keys"],
  leaderboard: [],
  bar: ["metric"],
  scatter: ["x", "y"],
  parallel: ["columns"],
  importance: ["metric"],
  grouped: ["group_by", "metric"],
  media: ["key"],
  table: ["path"],
  histogram: ["key"],
  lineage: [],
  run: [],
};

const SINGLE_RUN = new Set<PanelType>(["media", "table", "histogram", "lineage", "run"]);
const COMMON_REQUIRED = ["v", "id", "type", "app", "runs"];

export type ValidateResult =
  | { ok: true; spec: PanelSpec }
  | { ok: false; error: string };

function runsError(runs: unknown, single: boolean): string | null {
  if (typeof runs !== "object" || runs === null) return "runs must be a mapping";
  const r = runs as Record<string, unknown>;
  const pinned = Array.isArray(r.verstrs);
  if (pinned && "query" in r) return "runs takes either verstrs or a query, not both";
  if (single && !(pinned && (r.verstrs as unknown[]).length === 1))
    return "this panel type needs exactly one run in runs.verstrs";
  if (!pinned && typeof r.query !== "string") return "runs needs verstrs or query";
  return null;
}

export function validate(raw: unknown): ValidateResult {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw))
    return { ok: false, error: "panel spec must be a mapping" };
  const spec = raw as Record<string, unknown>;
  const missing = COMMON_REQUIRED.filter((k) => !(k in spec));
  if (missing.length) return { ok: false, error: `missing field(s): ${missing.join(", ")}` };
  if (spec.v !== 1) return { ok: false, error: `unsupported panel spec version ${String(spec.v)}` };
  const type = spec.type as PanelType;
  if (!(type in TYPE_REQUIRED)) return { ok: false, error: `unknown panel type ${String(spec.type)}` };
  const absent = TYPE_REQUIRED[type].filter((k) => !(k in spec));
  if (absent.length) return { ok: false, error: `${type} panel needs field(s): ${absent.join(", ")}` };
  const error = runsError(spec.runs, SINGLE_RUN.has(type));
  return error ? { ok: false, error } : { ok: true, spec: spec as PanelSpec };
}
