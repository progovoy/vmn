/** Plan 32: a board's metric columns without a declared goal rank nothing,
 *  so one hint says how to declare one (never a guessed goal). */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { MetricsSchema } from "../../types";
import GoalHint from "../GoalHint";

const renderHint = (metrics: string[], schema: MetricsSchema | null) =>
  render(<MemoryRouter><GoalHint metrics={metrics} schema={schema} base="/ws/w/app/my-app" /></MemoryRouter>);

describe("GoalHint", () => {
  it("counts the metric columns without a goal and links to the app settings", () => {
    renderHint(["loss", "acc", "lr"], { loss: { goal: "min" } });
    const hint = screen.getByRole("note");
    expect(hint).toHaveTextContent("2 metrics have no goal — declare goal: min|max in conf.yml or the app settings");
    expect(hint).toHaveAttribute("title", "No goal: acc, lr");
    expect(screen.getByRole("link", { name: "app settings" })).toHaveAttribute("href", "/ws/w/app/my-app/settings");
  });

  it("says one metric in the singular", () => {
    renderHint(["acc"], null);
    expect(screen.getByRole("note")).toHaveTextContent("1 metric has no goal");
  });

  it("is absent when every metric column has a goal, or there are none", () => {
    renderHint(["loss"], { loss: { goal: "min" } });
    expect(screen.queryByRole("note")).toBeNull();
    renderHint([], null);
    expect(screen.queryByRole("note")).toBeNull();
  });
});
