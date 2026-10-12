import { describe, it, expect } from "vitest";
import { closest } from "../closest";

describe("closest", () => {
  it("suggests a name within edit distance 2", () => {
    expect(closest("ml_ap", ["eval", "ml_app"])).toBe("ml_app");
    expect(closest("ml-rpeo", ["ml-repo", "team"])).toBe("ml-repo");
  });

  it("suggests a name the typo is a prefix of, however far", () => {
    expect(closest("res", ["resnet_large", "bert"])).toBe("resnet_large");
  });

  it("prefers the nearest of several candidates", () => {
    expect(closest("evl", ["eval2", "eval"])).toBe("eval");
  });

  it("suggests nothing when no name is close", () => {
    expect(closest("zzzzz", ["ml_app", "eval"])).toBeNull();
    expect(closest("ml_app", [])).toBeNull();
  });

  it("never suggests the name itself", () => {
    expect(closest("eval", ["eval"])).toBeNull();
  });
});
