/** A tiny inline histogram (plan 23 W1: a job's Spread). */
import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import Sparkline from "../Sparkline";

describe("Sparkline", () => {
  it("draws one bar per bin, the fullest at full height", () => {
    const { container } = render(<Sparkline counts={[1, 4, 2, 0]} title="distribution of loss over 7 runs" />);
    const bars = [...container.querySelectorAll("rect")];
    expect(bars).toHaveLength(4);
    const heights = bars.map((b) => Number(b.getAttribute("height")));
    expect(heights[1]).toBe(Math.max(...heights));
    expect(heights[3]).toBe(0);
    expect(container.querySelector("svg")).toHaveAttribute("aria-label", "distribution of loss over 7 runs");
    expect(container.querySelector("title")?.textContent).toBe("distribution of loss over 7 runs");
  });

  it("draws nothing without a value", () => {
    const { container } = render(<Sparkline counts={[0, 0]} title="x" />);
    expect(container.querySelector("svg")).toBeNull();
  });
});
