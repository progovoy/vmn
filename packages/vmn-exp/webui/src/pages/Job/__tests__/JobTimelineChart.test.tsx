/** The timeline's two charts share one x axis: the rate line steps across
 *  the same bucket edges as the area above it, and the axis label sits
 *  beside the area, not on it. */
import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import JobTimelineChart from "../JobTimelineChart";

const timeline = {
  bucket_sec: 60, start: 1_760_000_000,
  buckets: [
    { t: 1_760_000_000, started: 16, succeeded: 12, failed: 0 },
    { t: 1_760_000_060, started: 0, succeeded: 4, failed: 0 },
  ],
};

const xs = (d: string) => [...d.matchAll(/[ML]([\d.]+),/g)].map((m) => Number(m[1]));

describe("JobTimelineChart", () => {
  it("draws the rate across the area's full width, bucket edge to bucket edge", () => {
    const { container } = render(<JobTimelineChart timeline={timeline} />);
    const width = Number(container.querySelector(".job-area")!.getAttribute("viewBox")!.split(" ")[2]);
    const rate = xs(container.querySelector(".job-rate-line")!.getAttribute("d")!);
    expect(Math.min(...rate)).toBe(0);
    expect(Math.max(...rate)).toBe(width);
  });

  it("puts the axis maximum outside the plotted area", () => {
    const { container } = render(<JobTimelineChart timeline={timeline} />);
    expect(container.querySelector(".job-chart-frame .job-axis-max")).toBeNull();
    expect(container.querySelector(".job-axis-max")?.textContent).toBe("16");
  });
});
