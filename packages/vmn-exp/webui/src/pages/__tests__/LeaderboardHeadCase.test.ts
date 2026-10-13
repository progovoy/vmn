import { describe, it, expect } from "vitest";
import css from "../leaderboardTable.css?raw";

/** D3: a metric or param column header is a name, never uppercased. */
describe("leaderboardTable.css", () => {
  it.each(["m:", "p:"])("keeps %s column headers as typed", (prefix) => {
    const rule = new RegExp(`th\\[data-col-id\\^="${prefix}"\\][^{]*\\{([^}]*)\\}`).exec(css)?.[1] ?? "";
    expect(rule).toMatch(/text-transform:\s*none/);
  });
});
