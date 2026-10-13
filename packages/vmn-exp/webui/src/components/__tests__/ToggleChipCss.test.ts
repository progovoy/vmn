import { describe, it, expect } from "vitest";
import css from "../ToggleChip.css?raw";
import source from "../ToggleChip.tsx?raw";

describe("ToggleChip.css", () => {
  it("keeps a chip's label on one line (Log y never wraps out of a narrow toolbar)", () => {
    const rule = /button\.status-toggle\s*\{([^}]*)\}/.exec(css)?.[1] ?? "";
    expect(rule).toMatch(/white-space:\s*nowrap/);
    expect(source).toMatch(/import "\.\/ToggleChip\.css"/);
  });
});
