/** The palette's rows and sections (plan 19 §1.5), from what the shell knows
 *  plus the parsed command. Pure: the component only renders and routes. */
import { appTag } from "../../api";
import type { ModelRow } from "../../apiModels";
import type { ReportRow } from "../../apiReports";
import { DOCS_URL, type ShellContext } from "../../shell/contracts";
import type { AppRow, ExperimentRow, Workspace } from "../../types";
import { modelHref, relTime, runHref } from "../../util";
import { runSearchQuery } from "../../util/searchQuery";
import type { IconName } from "../shell/icons";
import type { CliIntent } from "./parseCliQuery";
import type { RecentEntry } from "./recents";
import { quoteArg } from "./tokenize";
import type { RefResolution, RefState } from "./useRefResolution";

export interface PaletteItem {
  id: string; icon: IconName; label: string;
  /** Mono text before the label (a run's `@N`). */
  prefix?: string; mono?: boolean; secondary?: string; title?: string;
  /** `command` as shown in the right column (without `vmn-exp `). */
  cli?: string;
  /** The full CLI equivalent, copied by ⇧↵. */
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
  ShellContext, "ws" | "app" | "appBase" | "isGit" | "readOnly" | "canAdmin" | "meta" | "workspaces"
>;
export interface PaletteInput {
  ctx: PaletteCtx; text: string; intent: CliIntent; refs: RefResolution;
  runs: ExperimentRow[]; searched: boolean; apps: AppRow[];
  models: ModelRow[]; reports: ReportRow[]; recents: RecentEntry[];
}

export const SECTION_CAP = 5;
const TYPED_RUNS = 8;
const RECENT_ICONS: Record<string, IconName> = { run: "run", app: "app", ws: "workspace", workspace: "workspace" };

const sh = (...words: string[]) => words.map(quoteArg).join(" ");
const vx = (...words: string[]) => sh("vmn-exp", ...words);
const enc = encodeURIComponent;
const runsCount = (n: number) => (n === 1 ? "1 run" : `${n} runs`);

function row(id: string, icon: IconName, label: string, extra: Partial<PaletteItem> = {}): PaletteItem {
  return { id, icon, label, ...extra, cli: extra.command?.replace(/^vmn-exp /, "") };
}
const errorRow = (message: string) => row("cmd:error", "command", message, { disabled: true });

export function capItems(section: PaletteSection, expanded: boolean) {
  if (expanded || section.items.length <= SECTION_CAP) return { items: section.items, more: 0 };
  return { items: section.items.slice(0, SECTION_CAP), more: section.items.length - SECTION_CAP };
}

function gotoItems(ctx: PaletteCtx): PaletteItem[] {
  const { ws, app, appBase: base } = ctx;
  const out: PaletteItem[] = [];
  if (base && app) {
    out.push(row("go:experiments", "experiments", "Experiments", { secondary: app, to: base, command: vx("list", app) }));
    if (ctx.isGit) {
      out.push(row("go:tree", "tree", "Stamp tree", { secondary: app, to: `${base}/tree`, command: sh("vmn", "show", app) }));
      out.push(row("go:actions", "actions", "Actions", { secondary: app, to: `${base}/actions` }));
    }
    out.push(row("go:compare", "command", "Compare runs…", { fill: "compare " }));
    out.push(row("go:overlay", "command", "Overlay curves…", { fill: "overlay " }));
    out.push(row("go:diff", "command", "Code diff…", { fill: "diff " }));
  }
  if (ws) {
    out.push(row("go:apps", "apps", "Apps", { secondary: ws, to: `/ws/${ws}` }));
    out.push(row("go:models", "models", "Models", { to: `/ws/${ws}/models`, command: vx("model", "list") }));
    out.push(row("go:reports", "reports", "Reports", { to: `/ws/${ws}/reports` }));
  }
  if (ctx.meta?.control_plane && ctx.canAdmin) out.push(row("go:tokens", "key", "API tokens", { to: "/tokens" }));
  out.push(row("go:docs", "external", "Docs: vmn-exp ui", { to: DOCS_URL, external: true }));
  if (base && app && ctx.isGit && !ctx.readOnly) {
    out.push(row("go:new", "run", "New run", { to: `${base}?new=1`, command: vx("create", app) }));
  }
  return out;
}

function runItem(r: ExperimentRow, base: string, app: string): PaletteItem {
  const ref = r.idx ? `@${r.idx}` : r.verstr;
  return row(`run:${r.verstr}`, "run", r.name || r.verstr, {
    prefix: r.idx ? ref : undefined, mono: !r.name, title: r.verstr,
    secondary: [r.status, r.note, relTime(r.timestamp)].filter(Boolean).join(" · "),
    to: runHref(base, r.verstr), command: vx("show", app, "-v", ref),
  });
}

const appItem = (ws: string, a: AppRow) => row(`app:${a.name}`, "app", a.name, {
  mono: true, secondary: runsCount(a.experiments), to: `/ws/${ws}/app/${appTag(a.name)}`, command: vx("list", a.name),
});
const wsItem = (w: Workspace) => row(`ws:${w.name}`, "workspace", w.name, {
  mono: true, secondary: w.store ?? w.path, title: w.store ?? w.path, to: `/ws/${w.name}`,
});
const modelItem = (ws: string, m: ModelRow) => row(`model:${m.name}`, "models", m.name, {
  mono: true, secondary: [m.kind ?? "model", m.latest_version ? `v${m.latest_version}` : ""].filter(Boolean).join(" · "),
  to: modelHref(ws, m.name), command: vx("model", "show", m.name),
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
  const { page } = intent;
  const { ws } = ctx;
  if (page === "docs") return [row("cmd:docs", "external", "Docs: vmn-exp ui", { to: DOCS_URL, external: true })];
  if (page === "tokens") {
    return ctx.meta?.control_plane && ctx.canAdmin ? [row("cmd:tokens", "key", "API tokens", { to: "/tokens" })]
      : [errorRow("API tokens need a control plane and the admin role")];
  }
  if (!ws) return [errorRow("name a workspace: ws <name>")];
  const base = intent.app && `/ws/${ws}/app/${appTag(intent.app)}`;
  switch (page) {
    case "models": return [row("cmd:models", "models", "Models", { to: `/ws/${ws}/models`, command: vx("model", "list") })];
    case "model": return [row("cmd:model", "models", `model ${intent.model}`, {
      to: modelHref(ws, intent.model!), command: vx("model", "show", intent.model!),
    })];
    case "reports": return [row("cmd:reports", "reports", "Reports", { to: `/ws/${ws}/reports` })];
    case "apps": return [row("cmd:apps", "apps", "Apps", { secondary: ws, to: `/ws/${ws}` })];
    case "actions": return [row("cmd:actions", "actions", "Actions", { secondary: intent.app, to: `${base}/actions` })];
    default: return [row("cmd:experiments", "experiments", "Experiments", {
      secondary: intent.app, to: base, command: vx("list", intent.app!),
    })];
  }
}

function refError(ref: string, state: RefState, app: string, apps: AppRow[]): string {
  if (state.state === "several") return `${ref} matches several runs; type more of it`;
  const n = Number(/^@(\d+)$/.exec(ref)?.[1]);
  const total = apps.find((a) => a.name === app)?.experiments;
  if (n && total !== undefined && n > total) {
    return total ? `${app} has ${runsCount(total)} (@1–@${total})` : `${app} has no runs yet`;
  }
  return `no run matches ${ref}`;
}

type RefIntent = Extract<CliIntent, { kind: "show" | "compare" | "overlay" }>;

function refCommand(intent: RefIntent, base: string, input: PaletteInput): PaletteItem[] {
  const refs = intent.kind === "show" ? [intent.ref] : intent.refs;
  const label = `${intent.kind} ${refs.join(" ")}`;
  const command = intent.kind === "overlay" ? undefined : vx(intent.kind, intent.app, ...refs.flatMap((r) => ["-v", r]));
  const states = refs.map((r) => input.refs.results[r] ?? { state: "pending" as const });
  if (input.refs.pending || states.some((s) => s.state === "pending")) {
    return [row("cmd:refs", "command", label, { mono: true, secondary: "resolving…", command })];
  }
  const runs = [];
  for (const [i, s] of states.entries()) {
    if (s.state !== "ok") return [errorRow(refError(refs[i], s, intent.app, input.apps))];
    runs.push(s.run);
  }
  const verstrs = runs.map((r) => r.verstr);
  const to = intent.kind === "show" ? runHref(base, verstrs[0])
    : intent.kind === "compare" ? `${base}/compare-runs?${verstrs.map((v) => `sel=${enc(v)}`).join("&")}`
    : `${base}/overlay?runs=${verstrs.map(enc).join(",")}`;
  const secondary = intent.kind === "show" ? runs[0].name || verstrs[0] : runsCount(runs.length);
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
  const base = `/ws/${ctx.ws}/app/${appTag(app)}`;
  const c = (label: string, extra: Partial<PaletteItem>, icon: IconName = "command") =>
    [row(`cmd:${intent.kind}`, icon, label, { mono: true, ...extra })];
  switch (intent.kind) {
    case "app": return c(`app ${app}`, { to: base, command: vx("list", app) }, "app");
    case "list": {
      const qs = [intent.query && `q=${enc(intent.query)}`, intent.archived && "archived=1"].filter(Boolean).join("&");
      const flags = [...(intent.query ? ["--query", intent.query] : []), ...(intent.archived ? ["--archived"] : [])];
      const label = ["list", intent.query, intent.archived ? "--archived" : ""].filter(Boolean).join(" ");
      return c(label, { secondary: "filter runs", to: qs ? `${base}?${qs}` : base, command: vx("list", app, ...flags) });
    }
    case "status": return c(`status ${intent.status}`, {
      secondary: "filter runs", to: `${base}?status=${intent.status}`,
      command: vx("list", app, "--query", `status = "${intent.status}"`),
    });
    case "create": return c("New run", { to: `${base}?new=1`, command: vx("create", app) }, "run");
    case "copy": return c(`${intent.verb} ${intent.ref}`, {
      secondary: "copy the command", copyOnEnter: true, command: vx(intent.verb, app, "-v", intent.ref),
    });
    case "tree": {
      const v = intent.version;
      return c(v ? `tree ${v}` : "tree", { to: `${base}/tree${v ? `?v=${enc(v)}` : ""}`, command: sh("vmn", "show", app) }, "tree");
    }
    case "goto": {
      const v = intent.version;
      const go = c(v ? `goto ${v}` : "goto", {
        secondary: "fill the goto form", to: `${base}/actions${v ? `?goto=${enc(v)}` : ""}`,
        command: v ? sh("vmn", "goto", "-v", v, app) : sh("vmn", "goto", app),
      }, "actions");
      return v ? [...go, row("cmd:goto-tree", "tree", "Open in stamp tree", { to: `${base}/tree?v=${enc(v)}` })] : go;
    }
    case "diff": {
      const qs = new URLSearchParams({ v: intent.from, ...(intent.to ? { to: intent.to } : {}) });
      const refs = [intent.from, ...(intent.to ? [intent.to] : [])];
      return c(`diff ${refs.join(" ")}`, {
        secondary: "code diff", to: `${base}/compare?${qs}`, command: vx("diff", app, ...refs.flatMap((r) => ["-v", r])),
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
  const runs = ctx.appBase && ctx.app ? input.runs.map((r) => runItem(r, ctx.appBase!, ctx.app!)) : [];
  const apps = ctx.ws ? input.apps.filter((a) => a.name !== ctx.app).map((a) => appItem(ctx.ws!, a)) : [];
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
    section("models", "Models", ctx.ws ? keep(input.models.map((m) => modelItem(ctx.ws!, m))) : []),
    section("reports", "Reports", ctx.ws ? keep(input.reports.map((r) => reportItem(ctx.ws!, r))) : []),
    section("workspaces", "Workspaces", keep(workspaces)),
  ]);
}
