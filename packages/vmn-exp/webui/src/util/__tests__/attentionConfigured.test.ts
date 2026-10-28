/** Plan 28 P1: the app's configured attention queries join the strip's
 *  parts after the built-in stuck and failed-in-24h ones, running last. */
import { describe, it, expect } from "vitest";
import { attentionParts } from "../attention";
import type { AppStatus, AttentionEntry } from "../../shell/contracts";

const NOW = Date.parse("2026-10-13T12:00:00Z");
const entry = (key: string, count: number, level: AttentionEntry["level"] = "warn"): AttentionEntry =>
  ({ key, label: key.replace("_", " "), level, count, q: `tags.health = "${key}"` });
const status = (attention: AttentionEntry[], o: Partial<AppStatus["counts"]> = {}, failed_recent = 0): AppStatus => ({
  total: 50, failed_recent, rollup: null, attention,
  counts: { created: 0, running: 0, stuck: 0, succeeded: 0, failed: 0, ...o },
});
const parts = (s: AppStatus, current = "") => attentionParts(s, current, NOW);

describe("configured attention parts", () => {
  it("come after stuck and failed in 24h, in config order, before running", () => {
    const s = status([entry("unstable", 3), entry("diverged", 2, "error")], { stuck: 1, running: 4 }, 2);
    expect(parts(s).map((p) => p.text)).toEqual(["1 stuck", "2 failed in 24h", "3 unstable", "2 diverged", "4 running"]);
  });

  it("leave out an entry that counts nothing", () => {
    const s = status([entry("unstable", 0), entry("diverged", 2, "error")]);
    expect(parts(s).map((p) => p.text)).toEqual(["2 diverged"]);
  });

  it("show the strip alone: a configured count needs attention, running alone does not", () => {
    expect(parts(status([entry("unstable", 1)], { running: 5 })).map((p) => p.text)).toEqual(["1 unstable", "5 running"]);
    expect(parts(status([entry("unstable", 0)], { running: 5 }))).toEqual([]);
    expect(parts(status([], { running: 5 }))).toEqual([]);
  });

  it("carry their level and key, the built-in parts none", () => {
    const [stuck, warn, error] = parts(status([entry("unstable", 1), entry("diverged", 1, "error")], { stuck: 1 }));
    expect(stuck.level).toBeUndefined();
    expect([warn.key, warn.level]).toEqual(["unstable", "warn"]);
    expect([error.key, error.level]).toEqual(["diverged", "error"]);
  });

  it("link to the board filtered by the query verbatim, replacing its filters", () => {
    const s = status([{ key: "late", label: "late", level: "warn", count: 2, q: 'status = "created" and timestamp < ago("1h")' }]);
    const [late] = parts(s, "?q=metrics.loss%20%3C%201&status=failed&branch=dev&search=x&sort=loss");
    const search = new URLSearchParams(late.search);
    expect(search.get("q")).toBe('status = "created" and timestamp < ago("1h")');
    for (const k of ["status", "branch", "search"]) expect(search.has(k)).toBe(false);
    expect(search.get("sort")).toBe("loss");
    expect(late.title).toBe('status = "created" and timestamp < ago("1h")');
  });

  it("read nothing from a status without attention", () => {
    const s: AppStatus = { ...status([], { stuck: 1 }), attention: undefined };
    expect(parts(s).map((p) => p.text)).toEqual(["1 stuck"]);
  });
});
