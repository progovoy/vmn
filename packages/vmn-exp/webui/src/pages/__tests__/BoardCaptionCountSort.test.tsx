import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import BoardCaption from "../BoardCaption";

const live = { running: false, paused: false, updatedAt: 0, onPaused: () => {}, onRefresh: () => {} };
const sortText = () => document.querySelector(".board-caption-sort")?.textContent;

describe("BoardCaption, count sort (plan 22 F10)", () => {
  it("says a count sort orders groups by how many runs, most first", () => {
    render(<BoardCaption sortLabel="c:failed" reversed={false} live={live} />);
    expect(sortText()).toBe("groups sorted by failed runs, most first");
    expect(screen.queryByText(/c:failed/)).toBeNull();
  });

  it("reads fewest first when reversed", () => {
    render(<BoardCaption sortLabel="c:total" reversed={true} live={live} />);
    expect(sortText()).toBe("groups sorted by total runs, fewest first");
  });

  it("keeps the metric wording for a metric sort", () => {
    render(<BoardCaption sortLabel="val_loss" reversed={false} live={live} />);
    expect(sortText()).toBe("sorted by val_loss, best first");
  });
});
