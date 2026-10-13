import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { screen } from "@testing-library/react";

vi.mock("uplot", async () => await import("./fakeUPlot"));

import { enableCanvas, resetInstances } from "./fakeUPlot";
import TrainingCurves from "../TrainingCurves";
import { renderWithClient } from "../../test-utils";

const originalGetContext = HTMLCanvasElement.prototype.getContext;
beforeEach(() => {
  resetInstances();
  enableCanvas();
});
afterEach(() => {
  HTMLCanvasElement.prototype.getContext = originalGetContext;
});

describe("TrainingCurves toolbar", () => {
  it("wraps its title and controls, so Log y stays inside a phone-width card", () => {
    renderWithClient(<TrainingCurves series={{ loss: [0, 1, 2].map((i) => ({ step: i, value: i, ts: null })) }} />);
    const group = screen.getByRole("heading", { name: "Training curves" }).parentElement!;
    expect(group).toContainElement(screen.getByRole("button", { name: /log y/i }));
    expect(group.style.flexWrap).toBe("wrap");
  });
});
