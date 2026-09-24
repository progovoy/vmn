import { describe, it, expect } from "vitest";
import { sameValue, stabilizeRows } from "../stableRows";

type R = { verstr: string; metrics: Record<string, number>; note?: string | null };

describe("sameValue", () => {
  it("compares plain JSON values structurally", () => {
    expect(sameValue({ a: [1, { b: null }] }, { a: [1, { b: null }] })).toBe(true);
    expect(sameValue({ a: 1 }, { a: 1, b: undefined })).toBe(false);
    expect(sameValue([1, 2], [2, 1])).toBe(false);
    expect(sameValue(null, {})).toBe(false);
  });
});

describe("stabilizeRows", () => {
  const a: R = { verstr: "a", metrics: { loss: 0.1 } };
  const b: R = { verstr: "b", metrics: { loss: 0.2 } };

  it("keeps each unchanged row's identity when another row changed", () => {
    const next = [{ verstr: "a", metrics: { loss: 0.1 } }, { verstr: "b", metrics: { loss: 0.3 } }];
    const out = stabilizeRows([a, b], next);
    expect(out[0]).toBe(a);
    expect(out[1]).not.toBe(b);
    expect(out[1].metrics.loss).toBe(0.3);
  });

  it("matches rows by verstr, so a reorder keeps identities", () => {
    const out = stabilizeRows([a, b], [{ ...b, metrics: { loss: 0.2 } }, { ...a, metrics: { loss: 0.1 } }]);
    expect(out[0]).toBe(b);
    expect(out[1]).toBe(a);
  });

  it("returns the previous array when nothing changed at all", () => {
    const prev = [a, b];
    expect(stabilizeRows(prev, [{ ...a, metrics: { loss: 0.1 } }, { ...b, metrics: { loss: 0.2 } }])).toBe(prev);
  });

  it("takes the new rows when there were none before", () => {
    const next = [a];
    expect(stabilizeRows(undefined, next)).toBe(next);
  });
});
