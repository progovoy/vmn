/** Plan 20 D5 (7): the run page lists the params that vary across the app's
 *  runs first, then the rest, each group in its own order. */
import { describe, it, expect } from "vitest";
import { paramsVariedFirst } from "../runParams";

const rows = (...params: Record<string, unknown>[]) => params.map((p) => ({ params: p }));

describe("paramsVariedFirst", () => {
  it("moves the params whose values differ among the rows to the front", () => {
    const own = { batch: 32, lr: 0.1, model: "resnet", seed: 1 };
    const others = rows({ batch: 32, lr: 0.01, model: "resnet", seed: 2 }, { batch: 32, lr: 0.1, model: "resnet", seed: 1 });
    expect(Object.keys(paramsVariedFirst(own, others))).toEqual(["lr", "seed", "batch", "model"]);
  });

  it("counts a param another run lacks as varying", () => {
    expect(Object.keys(paramsVariedFirst({ a: 1, b: 2 }, rows({ a: 1, b: 2 }, { a: 1 })))).toEqual(["b", "a"]);
  });

  it("keeps the params as they are without other rows to compare", () => {
    const own = { z: 1, a: 2 };
    expect(paramsVariedFirst(own, [])).toBe(own);
    expect(paramsVariedFirst(own, rows({ z: 1, a: 2 }))).toBe(own);
    expect(paramsVariedFirst(null, rows({ z: 1 }))).toBeNull();
  });
});
