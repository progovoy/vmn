import { describe, it, expect } from "vitest";
import { DOCS_URL } from "../../../shell/contracts";
import type { ExperimentRow } from "../../../types";
import { buildSections, capItems, SECTION_CAP, shortCli, type PaletteInput, type PaletteSection } from "../paletteItems";
import { parseCliQuery } from "../parseCliQuery";
import { fakeCtx } from "./fakeCtx";

const run = (idx: number, verstr: string, extra: Partial<ExperimentRow> = {}) =>
  ({ idx, verstr, name: null, note: null, timestamp: null, ...extra }) as ExperimentRow;

function build(over: Partial<PaletteInput> & { text?: string } = {}): PaletteSection[] {
  const ctx = over.ctx ?? fakeCtx({ app: "ml_app" });
  const text = over.text ?? "";
  const apps = over.apps ?? [{ name: "ml_app", experiments: 53, versions: 4 }, { name: "other", experiments: 1, versions: 0 }];
  return buildSections({
    ctx, text, apps,
    intent: over.intent ?? parseCliQuery(text, {
      apps: apps.map((a) => a.name), workspaces: ctx.workspaces.map((w) => w.name), app: ctx.app,
    }),
    refs: over.refs ?? {},
    runs: over.runs ?? [], searched: over.searched ?? false,
    models: over.models ?? [], reports: over.reports ?? [], recents: over.recents ?? [],
  });
}
const keys = (s: PaletteSection[]) => s.map((x) => x.key);
const section = (s: PaletteSection[], key: string) => s.find((x) => x.key === key)!;
const labels = (s: PaletteSection[], key: string) => section(s, key).items.map((i) => i.label);
const twoWs = fakeCtx({ app: "ml_app", workspaces: [{ name: "w", kind: "git" }, { name: "prod", kind: "store" }] });

describe("section order", () => {
  it("empty: Recent, Go to, Runs, Apps, Workspaces", () => {
    const s = build({
      ctx: twoWs, runs: [run(1, "0.1.0-dev.a")],
      recents: [{ label: "@1", to: "/ws/w/app/ml_app/run/x", kind: "run" }],
    });
    expect(keys(s)).toEqual(["recent", "goto", "runs", "apps", "workspaces"]);
    expect(s.map((x) => x.title)).toEqual(["Recent", "Go to", "Runs", "Apps", "Workspaces"]);
  });

  it("typed: Command first, then Runs, Go to, Apps, Models, Reports, Workspaces", () => {
    const s = build({
      ctx: fakeCtx({ app: "ml_app", workspaces: [{ name: "w", kind: "git" }, { name: "remote", kind: "git" }] }),
      text: "re", searched: true, runs: [run(2, "0.2.0-dev.re")],
      apps: [{ name: "ml_app", experiments: 2, versions: 0 }, { name: "re_app", experiments: 1, versions: 0 }],
      models: [{ name: "resnet", description: null, latest_version: 3, aliases: {} } as never],
      reports: [{ rid: "r1", title: "Weekly report", rev: 1 }],
    });
    expect(keys(s)).toEqual(["runs", "goto", "apps", "models", "reports", "workspaces"]);
    expect(section(s, "runs").title).toBe("Runs");
    const cmd = build({ text: "@54", refs: { "@54": { state: "pending" } } });
    expect(keys(cmd)[0]).toBe("command");
  });

  it("leaves out the current app and workspace", () => {
    const s = build({ ctx: twoWs });
    expect(labels(s, "apps")).toEqual(["other"]);
    expect(labels(s, "workspaces")).toEqual(["prod"]);
  });
});

describe("Go to", () => {
  it("lists every destination of an app in a git workspace", () => {
    const s = build({ ctx: fakeCtx({ app: "ml_app", meta: { version: "1", control_plane: true } }) });
    expect(labels(s, "goto")).toEqual([
      "Experiments", "Stamp tree", "Actions", "Compare runs…", "Overlay curves…", "Code diff…",
      "Apps", "Models", "Reports", "API tokens", "Docs: vmn-exp ui", "New run",
    ]);
    const items = section(s, "goto").items;
    expect(items.find((i) => i.label === "Compare runs…")!.fill).toBe("compare ");
    expect(items.find((i) => i.label === "Docs: vmn-exp ui")).toMatchObject({ to: DOCS_URL, external: true });
    expect(items.find((i) => i.label === "New run")!.to).toBe("/ws/w/app/ml_app?new=1");
    expect(items.find((i) => i.label === "Stamp tree")!.command).toBe("vmn show ml_app");
  });

  it("drops app pages and templates without an app", () => {
    const s = build({ ctx: fakeCtx({ app: undefined }) });
    expect(labels(s, "goto")).toEqual(["Apps", "Models", "Reports", "Docs: vmn-exp ui"]);
  });

  it("hides New run while read-only, and the git pages in a store workspace", () => {
    expect(labels(build({ ctx: fakeCtx({ app: "ml_app", readOnly: true }) }), "goto")).not.toContain("New run");
    const store = labels(build({ ctx: fakeCtx({ app: "ml_app", isGit: false }) }), "goto");
    expect(store).not.toContain("New run");
    expect(store).not.toContain("Stamp tree");
    expect(store).not.toContain("Actions");
    expect(store).toContain("Experiments");
  });

  it("gates API tokens like the sidebar: a control plane, and admin", () => {
    const cp = { version: "1", control_plane: true };
    expect(labels(build({ ctx: fakeCtx({ meta: cp, canAdmin: false }) }), "goto")).not.toContain("API tokens");
    expect(labels(build({ ctx: fakeCtx({ meta: { version: "1" } }) }), "goto")).not.toContain("API tokens");
    expect(labels(build({ ctx: fakeCtx({ meta: cp }) }), "goto")).toContain("API tokens");
  });
});

describe("caps", () => {
  it("shows at most 5 rows, then N more, expandable", () => {
    const goto = section(build(), "goto");
    expect(SECTION_CAP).toBe(5);
    const capped = capItems(goto, false);
    expect(capped.items).toHaveLength(5);
    expect(capped.more).toBe(goto.items.length - 5);
    expect(capItems(goto, true)).toEqual({ items: goto.items, more: 0 });
  });

  it("offers up to 8 typed runs, plus all matches in experiments", () => {
    const runs = Array.from({ length: 12 }, (_, i) => run(i + 1, `0.0.${i}-dev.x`));
    const s = section(build({ text: "dev", searched: true, runs }), "runs");
    expect(s.items).toHaveLength(8);
    expect(s.tail).toMatchObject({
      label: "All matches in experiments", icon: "chevron-right",
      to: `/ws/w/app/ml_app?q=${encodeURIComponent('verstr ~ "dev" or note ~ "dev"')}`,
    });
  });

  it("shows the 5 newest runs while empty", () => {
    const runs = Array.from({ length: 20 }, (_, i) => run(i + 1, `r${i}`));
    expect(section(build({ runs }), "runs").items).toHaveLength(5);
  });
});

describe("rows", () => {
  it("say runs, not experiments", () => {
    const s = build({ ctx: twoWs });
    expect(section(s, "apps").items[0]).toMatchObject({ label: "other", secondary: "1 run", command: "vmn-exp list other" });
    const many = build({ ctx: fakeCtx({ app: "x" }) });
    expect(section(many, "apps").items[0].secondary).toBe("53 runs");
  });

  it("show a run's @N, status word, age and CLI", () => {
    const r = run(54, "0.2.0-dev.abc", { name: "lr-sweep-3", status: "running" });
    const item = section(build({ runs: [r] }), "runs").items[0];
    expect(item).toMatchObject({
      prefix: "@54", label: "lr-sweep-3", title: "0.2.0-dev.abc", secondary: "running",
      to: "/ws/w/app/ml_app/run/0.2.0-dev.abc", command: "vmn-exp show ml_app -v @54",
    });
  });
});

describe("CLI commands", () => {
  const store = fakeCtx({
    app: "ml_app", isGit: false, workspace: { name: "w", kind: "store", store: "s3://team-exp/ml" },
  });

  it("are the full runnable command, with --store on a store workspace", () => {
    const s = build({ ctx: store, runs: [run(54, "0.2.0-dev.abc")] });
    expect(section(s, "runs").items[0].command).toBe("vmn-exp show ml_app -v @54 --store s3://team-exp/ml");
    expect(section(s, "goto").items.find((i) => i.label === "Experiments")!.command)
      .toBe("vmn-exp list ml_app --store s3://team-exp/ml");
    expect(section(s, "apps").items[0].command).toBe("vmn-exp list other --store s3://team-exp/ml");
    const typed = section(build({ ctx: store, text: "metrics.loss < 0.3" }), "command").items[0];
    expect(typed.command).toBe("vmn-exp list ml_app --query 'metrics.loss < 0.3' --store s3://team-exp/ml");
  });

  it("show a short form without the program name", () => {
    expect(shortCli("vmn-exp show ml_app -v @54")).toBe("show ml_app -v @54");
    expect(shortCli("vmn show ml_app")).toBe("vmn show ml_app");
    expect(shortCli(undefined)).toBeUndefined();
  });
});

describe("Command row", () => {
  const cmd = (over: Partial<PaletteInput> & { text: string }) => section(build(over), "command").items;

  it("reads resolving… until the refs land, then goes to the runs", () => {
    const pending = cmd({ text: "compare @3 @7", refs: {} });
    expect(pending[0]).toMatchObject({ label: "compare @3 @7", secondary: "resolving…" });
    const ok = (verstr: string, idx: number) => ({ state: "ok" as const, run: { verstr, idx, name: null } });
    const done = cmd({ text: "compare @3 @7", refs: { "@3": ok("a1", 3), "@7": ok("b2", 7) } });
    expect(done[0]).toMatchObject({ to: "/ws/w/app/ml_app/compare-runs?tab=table&sel=a1&sel=b2" });
    expect(done[0].disabled).toBeFalsy();
    expect(done[0].command).toBe("vmn-exp compare ml_app -v @3 -v @7");
  });

  it("opens overlay and diff on the Compare page's curves and code tabs", () => {
    const ok = (verstr: string, idx: number) => ({ state: "ok" as const, run: { verstr, idx, name: null } });
    const overlay = cmd({ text: "overlay @3 @7", refs: { "@3": ok("a1", 3), "@7": ok("b2", 7) } });
    expect(overlay[0]).toMatchObject({ to: "/ws/w/app/ml_app/compare-runs?tab=curves&sel=a1&sel=b2" });
    expect(cmd({ text: "diff @3 @7" })[0]).toMatchObject({ to: "/ws/w/app/ml_app/compare-runs?tab=code&sel=%403&sel=%407" });
    expect(cmd({ text: "diff @3" })[0]).toMatchObject({ to: "/ws/w/app/ml_app/compare-runs?tab=code&sel=%403" });
  });

  it("names a missing or ambiguous ref", () => {
    const none = cmd({ text: "@60", refs: { "@60": { state: "none" } } });
    expect(none[0]).toMatchObject({ label: "ml_app has 53 runs (@1–@53)", disabled: true });
    const gone = cmd({ text: "show 0.2.0.dev9", refs: { "0.2.0.dev9": { state: "none" } } });
    expect(gone[0]).toMatchObject({ label: "no run matches 0.2.0.dev9", disabled: true });
    const many = cmd({ text: "show 0.2.", refs: { "0.2.": { state: "several" } } });
    expect(many[0].label).toBe("0.2. matches several runs; type more of it");
  });

  it("names an ambiguous prefix before a ref it may have crowded out of the one request", () => {
    const results = { "@3": { state: "none" as const }, "0.2.0": { state: "several" as const } };
    const rows = cmd({ text: "compare @3 0.2.0", refs: results });
    expect(rows[0].label).toBe("0.2.0 matches several runs; type more of it");
  });

  it("refuses goto in a store workspace and goto or create while read-only", () => {
    expect(cmd({ text: "goto 1.2.0", ctx: fakeCtx({ app: "ml_app", isGit: false }) })[0])
      .toMatchObject({ label: "goto needs a git workspace", disabled: true });
    expect(cmd({ text: "goto 1.2.0", ctx: fakeCtx({ app: "ml_app", readOnly: true }) })[0].label).toBe("read-only server");
    expect(cmd({ text: "create", ctx: fakeCtx({ app: "ml_app", readOnly: true }) })[0].label).toBe("read-only server");
    expect(cmd({ text: "compare @3" })[0]).toMatchObject({ label: "compare needs at least 2 runs", disabled: true });
  });

  it("prefills goto and offers the stamp tree", () => {
    const rows = cmd({ text: "goto 1.2.0" });
    expect(rows.map((r) => r.to)).toEqual(["/ws/w/app/ml_app/actions?goto=1.2.0", "/ws/w/app/ml_app/tree?v=1.2.0"]);
    expect(rows[1].label).toBe("Open in stamp tree");
    expect(rows[0].command).toBe("vmn goto -v 1.2.0 ml_app");
  });

  it("goes to the leaderboard with the query", () => {
    const [row] = cmd({ text: "metrics.loss < 0.3" });
    expect(row.to).toBe(`/ws/w/app/ml_app?q=${encodeURIComponent("metrics.loss < 0.3")}`);
    expect(row.command).toBe("vmn-exp list ml_app --query 'metrics.loss < 0.3'");
    expect(cmd({ text: "list --archived" })[0].to).toBe("/ws/w/app/ml_app?archived=1");
    expect(cmd({ text: "status stuck" })[0].to).toBe("/ws/w/app/ml_app?status=stuck");
  });

  it("sets labels in sans and commands in mono", () => {
    expect(cmd({ text: "create" })[0]).toMatchObject({ label: "New run", mono: false });
    expect(cmd({ text: "status stuck" })[0]).toMatchObject({ label: "status stuck", mono: true });
  });

  it("copies restore instead of navigating", () => {
    const [row] = cmd({ text: "restore @3" });
    expect(row).toMatchObject({ copyOnEnter: true, command: "vmn-exp restore ml_app -v @3" });
    expect(row.to).toBeUndefined();
  });

  it("keeps a page out of Go to when the command already goes there", () => {
    const s = build({ text: "models" });
    expect(section(s, "command").items[0].to).toBe("/ws/w/models");
    expect(section(s, "goto")?.items.map((i) => i.to) ?? []).not.toContain("/ws/w/models");
  });
});
