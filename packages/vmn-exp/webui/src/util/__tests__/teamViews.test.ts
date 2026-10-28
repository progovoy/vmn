/** Plan 28 P4: team views (settings `experiment.ui.views`), their page's
 *  default and saving one into the settings. */
import { describe, it, expect } from "vitest";
import {
  defaultViewOf, hasViewParams, pageViews, placedSearch, withTeamView, type TeamView,
} from "../teamViews";
import { dumpYaml } from "../yamlDump";

const views: TeamView[] = [
  { name: "health", page: "runs", search: "?show=t%3Ahealth", default: true },
  { name: "by kind", page: "job", search: "?group=tags.kind", default: false },
  { name: "failed", page: "runs", search: "?status=failed", default: false },
];

describe("team views", () => {
  it("lists a page's views and finds its default", () => {
    expect(pageViews(views, "runs").map((v) => v.name)).toEqual(["health", "failed"]);
    expect(pageViews(undefined, "runs")).toEqual([]);
    expect(defaultViewOf(views, "runs")?.name).toBe("health");
    expect(defaultViewOf(views, "job")).toBeUndefined();
  });

  it("tells view params from where-am-I ones", () => {
    expect(hasViewParams("")).toBe(false);
    expect(hasViewParams("?view=all&kind=singles&tab=runs&sel=a&new=1")).toBe(false);
    expect(hasViewParams("?view=all&sort=loss")).toBe(true);
    expect(hasViewParams("?show=t%3Ahealth")).toBe(true);
  });

  it("keeps the page's place params a view leaves out", () => {
    expect(placedSearch("?tab=runs&sel=x", "?group=tags.kind")).toBe("?group=tags.kind&tab=runs");
    expect(placedSearch("?view=jobs", "?view=all&sort=loss")).toBe("?view=all&sort=loss");
    expect(placedSearch("", "")).toBe("");
  });

  it("adds a view to the settings, replacing one of the same page and name", () => {
    const settings = { metrics: { loss: { goal: "min" } }, ui: { views: [views[0], views[1]] } };
    const next = withTeamView(settings, { name: "health", page: "runs", search: "?sort=loss", default: false });
    expect(next.metrics).toEqual(settings.metrics);
    expect((next.ui as { views: TeamView[] }).views).toEqual([
      { name: "health", page: "runs", search: "?sort=loss" }, views[1],
    ]);
    expect(withTeamView({}, views[2])).toEqual({ ui: { views: [{ name: "failed", page: "runs", search: "?status=failed" }] } });
  });

  it("a new default takes the page's default from the others", () => {
    const next = withTeamView({ ui: { views } }, { name: "new", page: "runs", search: "", default: true });
    const saved = (next.ui as { views: TeamView[] }).views;
    expect(saved.filter((v) => v.default).map((v) => v.name)).toEqual(["new"]);
    expect(saved.find((v) => v.name === "health")).not.toHaveProperty("default");
  });
});

describe("dumpYaml", () => {
  it("writes block YAML with JSON scalars", () => {
    expect(dumpYaml({
      metrics: { loss: { goal: "min", hidden: false } },
      ui: { views: [{ name: "a b", search: "?x=1" }], stale_after_min: 5, empty: [], none: {} },
    })).toBe([
      "metrics:",
      "  loss:",
      '    goal: "min"',
      "    hidden: false",
      "ui:",
      "  views:",
      '    - name: "a b"',
      '      search: "?x=1"',
      "  stale_after_min: 5",
      "  empty: []",
      "  none: {}",
      "",
    ].join("\n"));
  });

  it("quotes keys a plain scalar can't hold and writes lists of scalars", () => {
    expect(dumpYaml({ metrics: { "cv/*": { hidden: true } }, l: [1, "x", null] })).toBe([
      "metrics:",
      '  "cv/*":',
      "    hidden: true",
      "l:",
      "  - 1",
      '  - "x"',
      "  - null",
      "",
    ].join("\n"));
  });
});
