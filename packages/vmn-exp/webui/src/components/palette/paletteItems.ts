/** The palette's rows and sections (plan 19 §1.5), from what the shell knows
 *  plus the parsed command. Pure: the component only renders and routes. */
import type { ModelRow } from "../../apiModels";
import type { ReportRow } from "../../apiReports";
import { storeUriOf, vmnCommand, vmnExpCommand } from "../../shell/cliCommands";
import { DOCS_URL, type ShellContext } from "../../shell/contracts";
import type { AppRow, Workspace } from "../../types";
import { appHref, fmtCount, modelHref, plural, relTime, runHref } from "../../util";
import type { PaletteRun } from "./usePaletteRuns";
import { runSearchQuery } from "../../util/searchQuery";
import { isOuterRun, outerLabel, outerRunCount } from "../../util/outerRun";
import { compareSearch } from "../../pages/Compare/selection";
import type { IconName } from "../shell/icons";
import { wsLocation } from "../ui";
import type { CliIntent, PageName } from "./parseCliQuery";
import type { RecentEntry } from "./recents";
import type { RefResolution, RefState } from "./useRefResolution";

export interface PaletteItem {
  id: string; icon: IconName; label: string;
  /** Mono text before the label (a run's `@N`). */
  prefix?: string; mono?: boolean; secondary?: string; title?: string;
  /** The full, runnable CLI equivalent, copied by ⇧↵. */
  command?: string;
  to?: string; external?: boolean;
  /** A template row: Enter puts this in the input instead of going. */
  fill?: string;
  /** Enter copies `command` (restore, rerun). */
  copyOnEnter?: boolean;
  disabled?: boolean;
}
/** `tail` is always shown after the capped rows. */
export interface PaletteSection { key: string; title: string; items: PaletteItem[]; tail?: PaletteItem }
export type PaletteCtx = Pick<
  ShellContext, "ws" | "workspace" | "app" | "appBase" | "isGit" | "readOnly" | "canAdmin" | "meta" | "workspaces"
>;
export interface PaletteInput {
  ctx: PaletteCtx; text: string; intent: CliIntent; refs: RefResolution;
  runs: PaletteRun[]; searched: boolean; apps: AppRow[];
  models: ModelRow[]; reports: ReportRow[]; recents: RecentEntry[];
}

export const SECTION_CAP = 5;
const TYPED_RUNS = 8;
const RECENT_ICONS: Record<string, IconName> = {
  run: "run", app: "app", ws: "workspace", workspace: "workspace", experiments: "experiments",
  tree: "tree", actions: "actions", models: "models", reports: "reports", key: "key", settings: "settings",
};

/** A command as the row's right column shows it: without `vmn-exp `. */
export const shortCli = (command?: string) => command?.replace(/^vmn-exp /, "");

const vx = (ctx: PaletteCtx, ...words: string[]) => vmnExpCommand(words, storeUriOf(ctx.workspace));
const vmn = (...words: string[]) => vmnCommand(words);
const enc = encodeURIComponent;

function row(id: string, icon: IconName, label: string, extra: Partial<PaletteItem> = {}): PaletteItem {
  return { id, icon, label, ...extra };
}
const errorRow = (message: string) => row("cmd:error", "command", message, { disabled: true });

export function capItems(section: PaletteSection, expanded: boolean) {
  if (expanded || section.items.length <= SECTION_CAP) return { items: section.items, more: 0 };
  return { items: section.items.slice(0, SECTION_CAP), more: section.items.length - SECTION_CAP };
}

type SharedPage = Exclude<PageName, "model">;
interface PageScope { ctx: PaletteCtx; ws: string; app?: string; base?: string }

/** The pages Go to and a typed command both offer: [icon, label, extra]. */
const PAGES: Record<SharedPage, (s: PageScope) => [IconName, string, Partial<PaletteItem>]> = {
  experiments: ({ ctx, app, base }) => ["experiments", "Experiments", { secondary: app, to: base, command: vx(ctx, "list", app!) }],
  actions: ({ app, base }) => ["actions", "Actions", { secondary: app, to: `${base}/actions` }],
  settings: ({ ctx, app, base }) => ["settings", "Settings", {
    secondary: app, to: `${base}/settings`, command: vx(ctx, "settings", app!, "show"),
  }],
  apps: ({ ws }) => ["apps", "Apps", { secondary: ws, to: `/ws/${ws}` }],
  models: ({ ctx, ws }) => ["models", "Models", { to: `/ws/${ws}/models`, command: vx(ctx, "model", "list") }],
  reports: ({ ws }) => ["reports", "Reports", { to: `/ws/${ws}/reports` }],
  tokens: () => ["key", "API tokens", { to: "/tokens" }],
  docs: () => ["external", "Docs: vmn-exp ui", { to: DOCS_URL, external: true }],
};
function pageRow(source: "go" | "cmd", page: SharedPage, scope: PageScope): PaletteItem {
  const [icon, label, extra] = PAGES[page](scope);
  return row(`${source}:${page}`, icon, label, extra);
}
const canSeeTokens = (ctx: PaletteCtx) => Boolean(ctx.meta?.control_plane && ctx.canAdmin);

function gotoItems(ctx: PaletteCtx): PaletteItem[] {
  const { ws = "", app, appBase: base } = ctx;
  const scope = { ctx, ws, app, base };
  const out: PaletteItem[] = [];
  if (base && app) {
    out.push(pageRow("go", "experiments", scope));
    if (ctx.isGit) {
      out.push(row("go:tree", "tree", "Stamp tree", { secondary: app, to: `${base}/tree`, command: vmn("show", app) }));
      out.push(pageRow("go", "actions", scope));
    }
    out.push(pageRow("go", "settings", scope));
    out.push(row("go:compare", "command", "Compare runs…", { fill: "compare " }));
    out.push(row("go:overlay", "command", "Overlay curves…", { fill: "overlay " }));
    out.push(row("go:diff", "command", "Code diff…", { fill: "diff " }));
  }
  if (ws) out.push(...(["apps", "models", "reports"] as const).map((p) => pageRow("go", p, scope)));
  if (canSeeTokens(ctx)) out.push(pageRow("go", "tokens", scope));
  out.push(pageRow("go", "docs", scope));
  if (base && app && ctx.isGit && !ctx.readOnly) {
    out.push(row("go:new", "run", "New run", { to: `${base}?new=1`, command: vx(ctx, "create", app) }));
  }
  return out;
}

/** `@1,903 name · in <job>` for a search hit inside a job; an outer run's `outer · N runs`. */
function runItem(r: PaletteRun, ctx: PaletteCtx, base: string, app: string): PaletteItem {
  const ref = r.idx ? `@${r.idx}` : r.verstr;
  const where = r.root_name ? `in ${r.root_name}` : null;
  const outer = isOuterRun(r) ? outerLabel(outerRunCount(r)) : null;
  return row(`run:${r.verstr}`, "run", r.name || r.verstr, {
    prefix: r.idx ? `@${fmtCount(r.idx)}` : undefined, mono: !r.name, title: r.verstr,
    secondary: [outer, where, r.status, r.note, relTime(r.timestamp)].filter(Boolean).join(" · "),
    to: runHref(base, r.verstr), command: vx(ctx, "show", app, "-v", ref),
  });
}

const appItem = (ctx: PaletteCtx, ws: string, a: AppRow) => row(`app:${a.name}`, "app", a.name, {
  mono: true, secondary: a.experiments === null ? "" : plural(a.experiments, "run"), to: appHref(ws, a.name), command: vx(ctx, "list", a.name),
});
const wsItem = (w: Workspace) => row(`ws:${w.name}`, "workspace", w.name, {
  mono: true, secondary: wsLocation(w), title: wsLocation(w), to: `/ws/${w.name}`,
});
const modelItem = (ctx: PaletteCtx, ws: string, m: ModelRow) => row(`model:${m.name}`, "models", m.name, {
  mono: true, secondary: [m.kind ?? "model", m.latest_version ? `v${m.latest_version}` : ""].filter(Boolean).join(" · "),
  to: modelHref(ws, m.name), command: vx(ctx, "model", "show", m.name),
});
const reportItem = (ws: string, r: ReportRow) => row(`report:${r.rid}`, "reports", r.title || r.rid, {
  secondary: "report", to: `/ws/${ws}/reports/${enc(r.rid)}`,
});
const recentItem = (r: RecentEntry) => row(`recent:${r.to}`, RECENT_ICONS[r.kind] ?? "page", r.label, { to: r.to });

/** A store workspace has no checkout; a read-only server takes no edits. */
function blockedReason(intent: CliIntent, ctx: PaletteCtx): string | null {
  const verb = intent.kind === "page" && intent.page === "actions" ? "actions" : intent.kind;
  if (["goto", "tree", "create", "actions"].includes(verb) && !ctx.isGit) return `${verb} needs a git workspace`;
  if ((verb === "goto" || verb === "create") && ctx.readOnly) return "read-only server";
  return null;
}

function pageCommand(intent: Extract<CliIntent, { kind: "page" }>, ctx: PaletteCtx): PaletteItem[] {
  const { page, app } = intent;
  const { ws } = ctx;
  if (page === "tokens" && !canSeeTokens(ctx)) return [errorRow("API tokens need a control plane and the admin role")];
  if (page !== "docs" && page !== "tokens" && !ws) return [errorRow("name a workspace: ws <name>")];
  if (page === "model") {
    return [row("cmd:model", "models", `model ${intent.model}`, {
      to: modelHref(ws!, intent.model!), command: vx(ctx, "model", "show", intent.model!),
    })];
  }
  return [pageRow("cmd", page, { ctx, ws: ws ?? "", app, base: app && appHref(ws!, app) })];
}


function refError(ref: string, state: RefState, app: string, apps: AppRow[]): string {
  if (state.state === "several") return `${ref} matches several runs; type more of it`;
  const n = Number(/^@(\d+)$/.exec(ref)?.[1]);
  const total = apps.find((a) => a.name === app)?.experiments;
  if (n && total != null && n > total) {
    return total ? `${app} has ${plural(total, "run")} (@1–@${total})` : `${app} has no runs yet`;
  }
  return `no run matches ${ref}`;
}

type RefIntent = Extract<CliIntent, { kind: "show" | "compare" | "overlay" }>;

function refCommand(intent: RefIntent, base: string, input: PaletteInput): PaletteItem[] {
  const refs = intent.kind === "show" ? [intent.ref] : intent.refs;
  const label = `${intent.kind} ${refs.join(" ")}`;
  const command = intent.kind === "overlay" ? undefined : vx(input.ctx, intent.kind, intent.app, ...refs.flatMap((r) => ["-v", r]));
  const states = refs.map((r) => input.refs[r] ?? { state: "pending" as const });
  if (states.some((s) => s.state === "pending")) {
    return [row("cmd:refs", "command", label, { mono: true, secondary: "resolving…", command })];
  }
  // An ambiguous prefix can fill the one request's limit and crowd out an
  // `@N`, so it is named first: typing more of it is the fix for both.
  const bad = states.findIndex((s) => s.state === "several");
  const failed = bad >= 0 ? bad : states.findIndex((s) => s.state !== "ok");
  if (failed >= 0) return [errorRow(refError(refs[failed], states[failed], intent.app, input.apps))];
  const runs = states.map((s) => (s as Extract<RefState, { state: "ok" }>).run);
  const verstrs = runs.map((r) => r.verstr);
  const to = intent.kind === "show" ? runHref(base, verstrs[0])
    : intent.kind === "compare" ? `${base}/compare-runs?${compareSearch("table", verstrs)}`
    : `${base}/compare-runs?${compareSearch("curves", verstrs)}`;
  const secondary = intent.kind === "show" ? runs[0].name || verstrs[0] : plural(runs.length, "run");
  return [row("cmd:refs", intent.kind === "show" ? "run" : "command", label, {
    mono: true, secondary, title: verstrs.join(" "), to, command,
  })];
}

function commandItems(input: PaletteInput): PaletteItem[] {
  const { intent, ctx } = input;
  if (intent.kind === "none") return [];
  if (intent.kind === "error") return [errorRow(intent.message)];
  const blocked = blockedReason(intent, ctx);
  if (blocked) return [errorRow(blocked)];
  if (intent.kind === "page") return pageCommand(intent, ctx);
  if (intent.kind === "ws") return [row("cmd:ws", "workspace", `ws ${intent.ws}`, { mono: true, to: `/ws/${intent.ws}` })];
  if (!ctx.ws) return [errorRow("name a workspace: ws <name>")];
  const { app } = intent;
  const base = appHref(ctx.ws, app);
  const c = (label: string, extra: Partial<PaletteItem>, icon: IconName = "command") =>
    [row(`cmd:${intent.kind}`, icon, label, { mono: true, ...extra })];
  switch (intent.kind) {
    case "app": return c(`app ${app}`, { to: base, command: vx(ctx, "list", app) }, "app");
    case "list": {
      const qs = [intent.query && `q=${enc(intent.query)}`, intent.archived && "archived=1"].filter(Boolean).join("&");
      const flags = [...(intent.query ? ["--query", intent.query] : []), ...(intent.archived ? ["--archived"] : [])];
      const label = ["list", intent.query, intent.archived ? "--archived" : ""].filter(Boolean).join(" ");
      return c(label, { secondary: "filter runs", to: qs ? `${base}?${qs}` : base, command: vx(ctx, "list", app, ...flags) });
    }
    case "status": return c(`status ${intent.status}`, {
      secondary: "filter runs", to: `${base}?status=${intent.status}`,
      command: vx(ctx, "list", app, "--query", `status = "${intent.status}"`),
    });
    case "create": return c("New run", { mono: false, to: `${base}?new=1`, command: vx(ctx, "create", app) }, "run");
    case "copy": return c(`${intent.verb} ${intent.ref}`, {
      secondary: "copy the command", copyOnEnter: true, command: vx(ctx, intent.verb, app, "-v", intent.ref),
    });
    case "tree": {
      const v = intent.version;
      return c(v ? `tree ${v}` : "tree", { to: `${base}/tree${v ? `?v=${enc(v)}` : ""}`, command: vmn("show", app) }, "tree");
    }
    case "goto": {
      const v = intent.version;
      const go = c(v ? `goto ${v}` : "goto", {
        secondary: "fill the goto form", to: `${base}/actions${v ? `?goto=${enc(v)}` : ""}`,
        command: v ? vmn("goto", "-v", v, app) : vmn("goto", app),
      }, "actions");
      return v ? [...go, row("cmd:goto-tree", "tree", "Open in stamp tree", { to: `${base}/tree?v=${enc(v)}` })] : go;
    }
    case "diff": {
      const refs = [intent.from, ...(intent.to ? [intent.to] : [])];
      return c(`diff ${refs.join(" ")}`, {
        secondary: "code diff", to: `${base}/compare-runs?${compareSearch("code", refs)}`, command: vx(ctx, "diff", app, ...refs.flatMap((r) => ["-v", r])),
      });
    }
    default: return refCommand(intent, base, input);
  }
}

const matches = (text: string, item: PaletteItem) => {
  const hay = [item.prefix, item.label, item.secondary].filter(Boolean).join(" ").toLowerCase();
  return text.toLowerCase().split(/\s+/).every((word) => hay.includes(word));
};
const section = (key: string, title: string, items: PaletteItem[], tail?: PaletteItem): PaletteSection =>
  ({ key, title, items, tail });

export function buildSections(input: PaletteInput): PaletteSection[] {
  const { ctx } = input;
  const text = input.text.trim();
  const runs = ctx.appBase && ctx.app ? input.runs.map((r) => runItem(r, ctx, ctx.appBase!, ctx.app!)) : [];
  const apps = ctx.ws ? input.apps.filter((a) => a.name !== ctx.app).map((a) => appItem(ctx, ctx.ws!, a)) : [];
  const workspaces = ctx.workspaces.filter((w) => w.name !== ctx.ws).map(wsItem);
  const goto = gotoItems(ctx);
  const nonEmpty = (sections: PaletteSection[]) => sections.filter((s) => s.items.length);
  if (!text) {
    return nonEmpty([
      section("recent", "Recent", input.recents.slice(0, SECTION_CAP).map(recentItem)),
      section("goto", "Go to", goto),
      section("runs", "Runs", runs.slice(0, SECTION_CAP)),
      section("apps", "Apps", apps),
      section("workspaces", "Workspaces", workspaces),
    ]);
  }
  const command = commandItems(input);
  const taken = new Set(command.map((c) => c.to).filter(Boolean));
  const keep = (items: PaletteItem[]) => items.filter((i) => !taken.has(i.to) && matches(text, i));
  const typedRuns = (input.searched ? runs : runs.filter((i) => matches(text, i))).slice(0, TYPED_RUNS);
  const allMatches = ctx.appBase && row("runs:all", "chevron-right", "All matches in experiments", {
    to: `${ctx.appBase}?q=${enc(runSearchQuery(text))}`,
  });
  return nonEmpty([
    section("command", "Command", command),
    section("runs", "Runs", typedRuns, allMatches || undefined),
    section("goto", "Go to", keep(goto)),
    section("apps", "Apps", keep(apps)),
    section("models", "Models", ctx.ws ? keep(input.models.map((m) => modelItem(ctx, ctx.ws!, m))) : []),
    section("reports", "Reports", ctx.ws ? keep(input.reports.map((r) => reportItem(ctx.ws!, r))) : []),
    section("workspaces", "Workspaces", keep(workspaces)),
  ]);
}
