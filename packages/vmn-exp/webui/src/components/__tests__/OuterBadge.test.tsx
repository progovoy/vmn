/** The `outer · N runs` badge: what marks an outer run wherever it shows. */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import OuterBadge from "../OuterBadge";
import { isOuterRun, outerRunCount } from "../../util/outerRun";
import type { ExperimentRow, JobRollup } from "../../types";

const rollup = (total: number) => ({ total }) as JobRollup;

describe("OuterBadge", () => {
  it("reads outer · N runs and links to the outer run's page", () => {
    render(<MemoryRouter><OuterBadge count={5} to="/ws/w/app/a/run/v1" /></MemoryRouter>);
    const link = screen.getByRole("link", { name: "outer · 5 runs" });
    expect(link).toHaveAttribute("href", "/ws/w/app/a/run/v1");
    expect(link).toHaveClass("outer-badge");
  });

  it("pluralizes one run and counts with separators", () => {
    const { rerender } = render(<MemoryRouter><OuterBadge count={1} to="/x" /></MemoryRouter>);
    expect(screen.getByRole("link")).toHaveTextContent("outer · 1 run");
    rerender(<MemoryRouter><OuterBadge count={2000} to="/x" /></MemoryRouter>);
    expect(screen.getByRole("link")).toHaveTextContent("outer · 2,000 runs");
  });

  it("says just outer without a count, and is plain text without a link", () => {
    render(<OuterBadge count={null} />);
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.getByText("outer")).toHaveClass("outer-badge");
  });
});

describe("outerRunCount", () => {
  it("prefers the row's subtree rollup total", () => {
    expect(outerRunCount({ job: rollup(7), children: ["a"] })).toBe(7);
  });

  it("falls back to the fleet counts, then the direct children", () => {
    expect(outerRunCount({ fleet: { expected: 9, counts: { succeeded: 3, failed: 1 } }, children: ["a"] })).toBe(4);
    expect(outerRunCount({ children: ["a", "b"] })).toBe(2);
  });

  it("is null when the row carries no count", () => {
    expect(outerRunCount({ kind: "outer" })).toBeNull();
  });
});

describe("isOuterRun", () => {
  const r = (extra: Partial<ExperimentRow>) => extra;
  it("is an outer kind, a row with a rollup or one with children", () => {
    expect(isOuterRun(r({ kind: "outer" }))).toBe(true);
    expect(isOuterRun(r({ job: rollup(2) }))).toBe(true);
    expect(isOuterRun(r({ children: ["a"] }))).toBe(true);
  });

  it("is not a single or inner run", () => {
    expect(isOuterRun(r({ kind: "single", children: [] }))).toBe(false);
    expect(isOuterRun(r({ kind: "inner", parent: "p" }))).toBe(false);
  });
});
