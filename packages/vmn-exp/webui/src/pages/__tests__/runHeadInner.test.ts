/** The run head's `N/M inner`: an ended outer run's lost runs have finished
 *  (failed) too, so an ended fleet whose stuck runs were lost reads done. */
import { describe, it, expect } from "vitest";
import { innerCount } from "../RunHead";

describe("innerCount", () => {
  it("counts succeeded and failed children done", () => {
    expect(innerCount({ expected: 16, counts: { succeeded: 10, failed: 2 } })).toBe("12/16 inner");
  });

  it("counts lost children done", () => {
    expect(innerCount({ expected: 16, counts: { succeeded: 12, failed: 1 }, lost: 3 })).toBe("16/16 inner");
  });
});
