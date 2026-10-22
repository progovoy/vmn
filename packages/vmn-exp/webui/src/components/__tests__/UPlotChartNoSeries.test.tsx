/** A faceted (mode 2) uPlot needs at least one series: its constructor reads
 *  series[1].facets. UPlotChart never builds one without. */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render } from "@testing-library/react";

vi.mock("uplot", async () => await import("./fakeUPlot"));

import { enableCanvas, instances, resetInstances } from "./fakeUPlot";
import UPlotChart from "../UPlotChart";

const originalGetContext = HTMLCanvasElement.prototype.getContext;
beforeEach(() => { resetInstances(); enableCanvas(); });
afterEach(() => { HTMLCanvasElement.prototype.getContext = originalGetContext; });

describe("UPlotChart", () => {
  it("builds no faceted plot without a series", async () => {
    render(<UPlotChart options={{ mode: 2, height: 100, series: [{}] }} data={[null] as never} />);
    await new Promise((r) => setTimeout(r, 50));
    expect(instances).toHaveLength(0);
  });
});
