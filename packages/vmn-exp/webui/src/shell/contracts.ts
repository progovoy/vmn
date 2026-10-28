/** The shell's shared contracts (plan 19 §2.2): types, storage keys and the RunLabel helper,
 *  so every shell unit and page builds against the same shapes. */
import type { Meta, Role, Workspace } from "../types";
import type { Freshness } from "../util/freshness";
import type { Indexing } from "../util/indexing";

export type RouteId =
  | "home" | "tokens" | "apps" | "experiments" | "run" | "compare-runs"
  | "tree" | "actions" | "models" | "model" | "reports" | "report"
  | "report-edit" | "not-found" | "sign-in" | "app-settings";
/** Every route's `handle` (routes.tsx). */
export interface RouteHandle { id: RouteId; wide?: boolean }

export interface GitContext {
  branch: string | null; detached: boolean; head: string | null;
  head_short: string | null; dirty: boolean | null; store: string; error?: string;
}
export interface AppStatus {
  total: number;
  counts: Record<"created" | "running" | "stuck" | "succeeded" | "failed", number>;
  /** Runs an ended outer run settled, never in `counts` (status_summary.py). */
  never_started?: number;
  lost?: number;
  failed_recent: number;
  rollup: "stuck" | "failed" | "running" | null;
  /** While a store's index still loads (routes_shell.py). */
  indexing?: Indexing;
  /** How fresh the served index is (routes_shell.py); absent inline. */
  freshness?: Freshness;
  /** The app's configured attention queries (plan 28 P1), in config order. */
  attention?: AttentionEntry[];
}
/** One `experiment.ui.attention` query and the runs it matches now; *q* is
 *  the query text the board filters by. A query that does not compile
 *  counts null, with its *error*. */
export interface AttentionEntry {
  key: string; label: string; level: AttentionLevel; count: number | null; q: string; error?: string;
}
export type AttentionLevel = "warn" | "error";
export interface AuthHints { token: boolean; oidc: boolean; login_url: string | null }

/** What pages may read (usePageScope): meta + workspaces only, no router
 *  matches, so it works under a plain MemoryRouter. */
export interface PageScope {
  ws?: string; workspace?: Workspace; workspaces: Workspace[];
  /** `workspace?.kind !== "store"` (true while unknown). */
  isGit: boolean;
  meta?: Meta;
  metaStatus: "loading" | "ok" | "unauthorized" | "forbidden" | "unreachable";
  /** `meta.auth?.enabled ?? false` */
  authEnabled: boolean;
  /** `workspace.role ?? meta.role ?? null` */
  role: Role | null;
  readOnly: boolean;
  /** The first read-only reason that applies (§2.2), else null. */
  readOnlyReason: string | null;
  /** `!authEnabled || meta.role === "admin"`: the global gate of /tokens and POST /workspaces. */
  canAdmin: boolean;
  /** `metaStatus === "ok" && !meta.read_only && canAdmin`: "Attach a checkout" may be offered. */
  canAttach: boolean;
}

/** What every shell component reads (useShellContext). */
export interface ShellContext extends PageScope {
  routeId: RouteId;
  /** The deepest match's params. */
  params: Record<string, string | undefined>;
  search: URLSearchParams;
  pathname: string;
  /** Whether `ws` came from the URL (else from lastWorkspace() on a global route). */
  wsFromUrl: boolean;
  /** The app in tag form / name form. */
  appTag?: string; app?: string;
  /** `/ws/${ws}/app/${appTag}` */
  appBase?: string;
  /** Whether the deepest route asks for the full content width. */
  wide?: boolean;
  override: "not-found" | "sign-in" | null;
}

export interface RunLabel { verstr: string; idx: number | null; name: string | null }
/** A row's label; what an older server omits is null. */
export const runLabelOf = (r: { verstr: string; idx?: number | null; name?: string | null }): RunLabel =>
  ({ verstr: r.verstr, idx: r.idx ?? null, name: r.name ?? null });
export interface Crumb { label: string; to?: string; mono?: boolean; title?: string; run?: RunLabel }
export interface CliCommand { label: string; command: string }
export interface CrumbInput {
  routeId: RouteId; ws?: string; app?: string; appTag?: string;
  params: Record<string, string | undefined>; search: URLSearchParams;
  /** `storeUri` set means a store workspace. */
  run?: RunLabel; reportTitle?: string; storeUri?: string;
}

export type NotFoundProps =
  | { kind: "route"; pathname: string }
  | { kind: "workspace"; ws: string }
  | { kind: "app"; ws: string; appTag: string }
  | { kind: "run"; ws: string; appTag: string; runRef: string }
  | { kind: "model"; ws: string; name: string }
  | { kind: "report"; ws: string; rid: string }
  | { kind: "control-plane" }
  | { kind: "needs-git"; ws: string; appTag: string; page: "tree" | "actions" };

/** sessionStorage: the ui token (or API token) the user signed in with. */
export const TOKEN_KEY = "vmn_token";
export const RETURN_TO_KEY = "vmn-exp:return-to";
export const LAST_WS_KEY = "vmn-exp:last-ws";
/** sessionStorage: `{ws: appTag}`, the app last opened in each workspace. */
export const LAST_APP_KEY = "vmn-exp:last-app";
export const RECENT_KEY = "vmn-exp:recent";
export const DOCS_URL = "https://github.com/progovoy/vmn/blob/master/docs/vmn-exp/ui.md";
