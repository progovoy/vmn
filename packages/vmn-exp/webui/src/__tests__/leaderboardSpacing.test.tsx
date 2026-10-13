import { describe, it, expect, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import LeaderboardFilter from "../components/LeaderboardFilter";
import LeaderboardCharts from "../pages/LeaderboardCharts";

vi.mock("../apiReports", () => ({
  apiReports: { listReports: vi.fn(() => Promise.resolve({ reports: [] })) },
}));

describe("leaderboard control spacing", () => {
  it("lays the filter controls out in one spaced filter bar", () => {
    const { container } = render(<LeaderboardFilter rows={[]} onSimilarChange={() => {}} />);
    const bar = container.firstElementChild as HTMLElement;
    expect(bar).toHaveClass("filter-bar");
    // Spacing comes from the stylesheet, not per-instance inline overrides.
    expect(bar.getAttribute("style")).toBeNull();
    expect(screen.getByRole("textbox", { name: "Filter query" })).toHaveClass("filter-control");
    expect(screen.getByRole("combobox")).toHaveClass("filter-control");
  });

  it("groups the chart views as one segmented control", () => {
    render(
      <QueryClientProvider client={new QueryClient()}><MemoryRouter>
        <LeaderboardCharts
          view="bar" onView={() => {}} rows={[]} metricCols={[]} paramCols={[]} schema={null}
          onBrush={() => {}} importance={{ ws: "w", app: "a", filter: {} }}
        />
      </MemoryRouter></QueryClientProvider>,
    );
    const group = screen.getByRole("group", { name: "Chart type" });
    expect(group).toHaveClass("segmented");
    for (const name of ["Trend", "Bar", "Scatter", "Parallel", "Grouped", "Importance"]) {
      expect(within(group).getByRole("button", { name })).toBeInTheDocument();
    }
    expect(within(group).getByRole("button", { name: "Bar" })).toHaveAttribute("aria-pressed", "true");
  });
});
