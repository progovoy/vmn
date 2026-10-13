/** Plan 20 E5: the y axis width varies with its labels, so the tooltip
 *  offsets by the plot's real left edge, not a fixed axis width. */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import CurveTooltip from "../CurveTooltip";
import { Y_AXIS_SIZE } from "../../util/curveOptions";

const series = [{ key: "a", label: "a", color: "red", xs: new Float64Array(), ys: new Float64Array() }];
const rows = [{ key: "a", x: 1, value: 2 }];
const show = (cursor: { left: number; top: number; x: number; y: number; plotLeft?: number }) =>
  render(<CurveTooltip rows={rows} series={series} cursor={cursor} width={0} formatX={String} />);

describe("CurveTooltip offset", () => {
  it("opens beside the cursor past the plot's measured left edge", () => {
    show({ left: 10, top: 20, x: 1, y: 2, plotLeft: 80 });
    expect(screen.getByTestId("curve-tooltip")).toHaveStyle({ left: "102px" });
  });

  it("falls back to the default axis width when the edge is unknown", () => {
    show({ left: 10, top: 20, x: 1, y: 2 });
    expect(screen.getByTestId("curve-tooltip")).toHaveStyle({ left: `${10 + Y_AXIS_SIZE + 12}px` });
  });
});
