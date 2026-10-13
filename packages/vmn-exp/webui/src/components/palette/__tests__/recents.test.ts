import { describe, it, expect, beforeEach } from "vitest";
import { RECENT_KEY } from "../../../shell/contracts";
import { forgetRecent, pushRecent, readRecents, recentKindOf } from "../recents";

beforeEach(() => localStorage.clear());

const entry = (i: number) => ({ label: `run ${i}`, to: `/ws/w/app/a/run/${i}`, kind: "run" });

describe("recents", () => {
  it("lists the newest first, stored under the shared key", () => {
    pushRecent(entry(1));
    pushRecent(entry(2));
    expect(readRecents().map((r) => r.label)).toEqual(["run 2", "run 1"]);
    expect(JSON.parse(localStorage.getItem(RECENT_KEY)!)).toHaveLength(2);
  });

  it("keeps at most 20", () => {
    for (let i = 0; i < 25; i++) pushRecent(entry(i));
    const all = readRecents();
    expect(all).toHaveLength(20);
    expect(all[0].label).toBe("run 24");
    expect(all[19].label).toBe("run 5");
  });

  it("moves a revisited destination to the front instead of repeating it", () => {
    pushRecent(entry(1));
    pushRecent(entry(2));
    pushRecent({ ...entry(1), label: "renamed" });
    expect(readRecents().map((r) => r.label)).toEqual(["renamed", "run 2"]);
  });

  it("survives a corrupt or foreign value", () => {
    localStorage.setItem(RECENT_KEY, "{not json");
    expect(readRecents()).toEqual([]);
    localStorage.setItem(RECENT_KEY, JSON.stringify([{ to: 1 }, entry(3)]));
    expect(readRecents()).toEqual([entry(3)]);
    pushRecent(entry(4));
    expect(readRecents().map((r) => r.label)).toEqual(["run 4", "run 3"]);
  });

  it("forgets a destination that turned out missing", () => {
    pushRecent(entry(1));
    pushRecent(entry(2));
    forgetRecent(entry(1).to);
    expect(readRecents().map((r) => r.label)).toEqual(["run 2"]);
  });

  it("files each route under the icon Go to uses for it", () => {
    expect(recentKindOf("run")).toBe("run");
    expect(recentKindOf("experiments")).toBe("app");
    expect(recentKindOf("apps")).toBe("ws");
    expect(recentKindOf("tree")).toBe("tree");
    expect(recentKindOf("actions")).toBe("actions");
    expect(recentKindOf("models")).toBe("models");
    expect(recentKindOf("model")).toBe("models");
    expect(recentKindOf("reports")).toBe("reports");
    expect(recentKindOf("report")).toBe("reports");
    expect(recentKindOf("report-edit")).toBe("reports");
    expect(recentKindOf("tokens")).toBe("key");
    expect(recentKindOf("compare-runs")).toBe("experiments");
    expect(recentKindOf("home")).toBe("workspace");
  });
});
