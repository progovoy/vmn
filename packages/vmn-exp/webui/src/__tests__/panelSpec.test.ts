import { describe, expect, it } from "vitest";
import { validate } from "../reports/panelSpec";
import schema from "../reports/panelSpec.schema.json";

const base = { v: 1, id: "p1", app: "a" };

describe("panelSpec.validate", () => {
  it("accepts a valid bar panel", () => {
    expect(validate({ ...base, type: "bar", runs: { query: "x = 1" }, metric: "m" }).ok).toBe(true);
  });
  it("reports unknown types without throwing", () => {
    const r = validate({ ...base, type: "sankey", runs: { verstrs: ["a"] } });
    expect(r).toEqual({ ok: false, error: "unknown panel type sankey" });
  });
  it("rejects prototype keys as types", () => {
    const r = validate({ ...base, type: "toString", runs: { verstrs: ["a"] } });
    expect(r).toEqual({ ok: false, error: "unknown panel type toString" });
  });
  it("requires type-specific fields", () => {
    expect(validate({ ...base, type: "scatter", runs: { verstrs: ["a"] }, x: "lr" }).ok).toBe(false);
  });
  it("requires exactly one run for single-run types", () => {
    expect(validate({ ...base, type: "run", runs: { verstrs: ["a", "b"] } }).ok).toBe(false);
    expect(validate({ ...base, type: "run", runs: { query: "x = 1" } }).ok).toBe(false);
    expect(validate({ ...base, type: "run", runs: { verstrs: ["a"] } }).ok).toBe(true);
  });
  it("matches the schema's type list", () => {
    const types = schema.oneOf.map((b) => b.properties.type.const).sort();
    for (const t of types) {
      const r = validate({ ...base, type: t, runs: { verstrs: ["a"] } });
      if (!r.ok) expect(r.error).not.toMatch(/unknown panel type/);
    }
  });
});
