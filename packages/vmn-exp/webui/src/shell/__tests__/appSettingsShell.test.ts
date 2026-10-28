/** Plan 28 A0: the app settings page in the shell: crumbs, title, CLI twin,
 *  ⌘K's typed command and Recent. */
import { describe, it, expect } from "vitest";
import { cliFor } from "../cliCommands";
import type { CrumbInput } from "../contracts";
import { crumbsFor, isAppRoute } from "../crumbs";
import { titleFor } from "../titles";
import { recentKindOf } from "../../components/palette/recents";
import { buildSections } from "../../components/palette/paletteItems";
import { parseCliQuery } from "../../components/palette/parseCliQuery";
import { fakeCtx } from "../../components/palette/__tests__/fakeCtx";

const input = (extra: Partial<CrumbInput> = {}): CrumbInput => ({
  routeId: "app-settings", ws: "ml-repo", app: "ml_app", appTag: "ml_app",
  params: {}, search: new URLSearchParams(), ...extra,
});

describe("the app settings route", () => {
  it("is an app route: the app links to its experiments, settings is the leaf", () => {
    expect(isAppRoute("app-settings")).toBe(true);
    expect(crumbsFor(input())).toEqual([
      { label: "ml_app", mono: true, to: "/ws/ml-repo/app/ml_app" }, { label: "settings" },
    ]);
  });

  it("is titled settings · app", () => {
    expect(titleFor(input())).toBe("settings · ml_app — vmn-exp");
  });

  it("copies vmn-exp settings show, with --store on a store workspace", () => {
    expect(cliFor(input()).map((c) => c.command)).toEqual(["vmn-exp settings ml_app show"]);
    expect(cliFor(input({ storeUri: "s3://b/p" }))[0].command)
      .toBe("vmn-exp settings ml_app show --store s3://b/p");
  });

  it("is a Recent of its own kind", () => {
    expect(recentKindOf("app-settings")).toBe("settings");
  });
});

describe("⌘K settings <app>", () => {
  const ctx = fakeCtx({ app: "ml_app" });
  const scope = { apps: ["ml_app"], workspaces: ["w"], app: "ml_app" };

  it("parses to the app's settings page", () => {
    expect(parseCliQuery("settings", scope)).toEqual({ kind: "page", page: "settings", app: "ml_app" });
    expect(parseCliQuery("vmn-exp settings ml_app show", scope))
      .toEqual({ kind: "page", page: "settings", app: "ml_app" });
  });

  it("offers a row going there, with its CLI twin", () => {
    const text = "settings ml_app";
    const sections = buildSections({
      ctx, text, intent: parseCliQuery(text, scope), refs: {}, runs: [], searched: false,
      apps: [{ name: "ml_app", experiments: 1, versions: 0 }], models: [], reports: [], recents: [],
    });
    const row = sections.flatMap((s) => s.items).find((i) => i.id === "cmd:settings");
    expect(row).toMatchObject({
      label: "Settings", to: "/ws/w/app/ml_app/settings", command: "vmn-exp settings ml_app show",
    });
  });
});
