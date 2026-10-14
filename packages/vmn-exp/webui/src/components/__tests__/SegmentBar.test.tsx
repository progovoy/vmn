/** One segmented run bar for group headers, Jobs rows and the job header. */
import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import SegmentBar from "../SegmentBar";
import segCss from "../segmentBar.css?raw";

describe("SegmentBar", () => {
  it("draws a toned span per segment at its width", () => {
    const { container } = render(
      <SegmentBar className="group-bar" segments={[{ tone: "done", pct: 75 }, { tone: "failed", pct: 25 }]} aria-hidden="true" />,
    );
    const bar = container.firstElementChild as HTMLElement;
    expect(bar).toHaveClass("seg-bar", "group-bar");
    expect(bar).toHaveAttribute("aria-hidden", "true");
    const segs = [...bar.querySelectorAll<HTMLElement>(".bar-seg")];
    expect(segs.map((s) => [s.dataset.tone, s.style.width])).toEqual([["done", "75%"], ["failed", "25%"]]);
    expect(segs[0]).toHaveClass("tone-done", "group-bar-seg");
  });

  it("passes progressbar aria through", () => {
    const { container } = render(
      <SegmentBar className="job-head-bar" segments={[]} role="progressbar" aria-valuenow={3} aria-label="3 done" />,
    );
    expect(container.firstElementChild).toHaveAttribute("role", "progressbar");
    expect(container.firstElementChild).toHaveAttribute("aria-valuenow", "3");
  });

  it("colours each tone once, in one stylesheet", () => {
    for (const tone of ["done", "failed", "stuck", "running"]) {
      expect(segCss).toMatch(new RegExp(`\\.bar-seg\\.tone-${tone}\\s*\\{`));
    }
  });
});
