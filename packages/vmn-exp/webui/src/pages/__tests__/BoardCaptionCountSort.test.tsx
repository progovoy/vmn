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

describe("BoardCaption, a metric without a goal (plan 32)", () => {
  it("says low first, not best first", () => {
    render(<BoardCaption sortLabel="grad_norm" reversed={false} order="asc" goal={null} live={live} />);
    expect(sortText()).toBe("sorted by grad_norm, low first (no goal)");
  });

  it("says high first when sorted descending", () => {
    render(<BoardCaption sortLabel="grad_norm" reversed={true} order="desc" goal={null} live={live} />);
    expect(sortText()).toBe("sorted by grad_norm, high first (no goal)");
  });

  it("keeps best first for a metric with a goal", () => {
    render(<BoardCaption sortLabel="cost" reversed={false} order="asc" goal="min" live={live} />);
    expect(sortText()).toBe("sorted by cost, best first");
  });
});
