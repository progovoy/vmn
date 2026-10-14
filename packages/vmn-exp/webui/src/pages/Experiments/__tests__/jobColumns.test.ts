/** The Jobs view's `#` column (plan 23): a six-digit `@N` never truncates. */
import { describe, it, expect } from "vitest";
import { CELL_CLASSES, JOB_COLUMNS } from "../jobColumns";

const at = JOB_COLUMNS.findIndex((c) => c.id === "idx");

describe("the Jobs view's # column", () => {
  it("is the board's run-number cell: 12px mono (styles.css td.idx-cell)", () => {
    expect(CELL_CLASSES[at].split(" ")).toContain("idx-cell");
  });

  it("fits `@100000` in 12px mono beside the cell's 10px + 10px padding", () => {
    const MONO_12PX = 7.3; // IBM Plex Mono advances 0.6em, rounded up
    const PADDING = 20;
    expect(JOB_COLUMNS[at].width).toBeGreaterThanOrEqual(Math.ceil("@100000".length * MONO_12PX + PADDING));
  });
});
