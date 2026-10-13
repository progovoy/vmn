import { describe, it, expect } from "vitest";
import css from "../RunChanges.css?raw";

describe("RunChanges.css", () => {
  it("keeps metric names as typed (D3): the row headers undo th's uppercase", () => {
    const rule = /\.changes-metrics th\[scope="row"\]\s*\{([^}]*)\}/.exec(css)?.[1] ?? "";
    expect(rule).toMatch(/text-transform:\s*none/);
  });
});
