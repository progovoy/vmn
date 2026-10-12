import { describe, it, expect } from "vitest";
import { runLabelOf } from "../contracts";

describe("runLabelOf", () => {
  it("keeps a row's verstr, idx and name", () => {
    expect(runLabelOf({ verstr: "0.1.0-dev.a", idx: 3, name: "lr-3" }))
      .toEqual({ verstr: "0.1.0-dev.a", idx: 3, name: "lr-3" });
  });
  it("fills what an older server omits with null", () => {
    expect(runLabelOf({ verstr: "v" })).toEqual({ verstr: "v", idx: null, name: null });
  });
});
