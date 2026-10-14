/** The board's table fills what the page leaves below its top, so the page
 *  itself never scrolls too (one scroll, not a scroll inside a scroll). */
import { describe, it, expect } from "vitest";
import { fillHeight, MIN_FILL_HEIGHT } from "../fillHeight";

const page = { viewport: 1000, elTop: 400, below: 200 };

describe("fillHeight", () => {
  it("leaves the page exactly its viewport: the table takes what the rest leaves", () => {
    // Below the table in its column: 200 px (caption, CLI line, padding).
    expect(fillHeight(page)).toBe(1000 - 400 - 200);
  });

  it("never shrinks the table under a usable height on a short screen", () => {
    expect(fillHeight({ ...page, viewport: 500 })).toBe(MIN_FILL_HEIGHT);
  });
});
