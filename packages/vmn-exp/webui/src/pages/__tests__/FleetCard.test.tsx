import { describe, it, expect } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { Fleet } from "../../types";
import { FleetCard } from "../RunSections";

const fleet: Fleet = {
  expected: 5,
  counts: { running: 2, succeeded: 1, failed: 1, stuck: 0, created: 0, waiting: 1 },
  children: [
    { verstr: "1.0-dev.abc.pod1", status: "running" as const, progress: 3, progress_total: 10 },
    { verstr: "1.0-dev.abc.pod2", status: "running" as const, progress: 7, progress_total: 10 },
    { verstr: "1.0-dev.abc.pod3", status: "succeeded" as const, progress: 10, progress_total: 10 },
    { verstr: "1.0-dev.abc.pod4", status: "failed" as const, progress: null, progress_total: null },
  ],
};

function renderFleet(f: Fleet = fleet) {
  return render(
    <MemoryRouter>
      <FleetCard fleet={f} runUrl={(v) => `/run/${v}`} />
    </MemoryRouter>,
  );
}

describe("FleetCard", () => {
  it("renders the fleet eyebrow header", () => {
    renderFleet();
    expect(screen.getByText("fleet")).toBeInTheDocument();
  });

  it("renders non-zero status counts", () => {
    const { container } = renderFleet();
    // running=2, succeeded=1, failed=1, waiting=1
    expect(screen.getByText("2")).toBeInTheDocument();
    // Check summary section has labels for non-zero statuses
    const summary = container.querySelector(".fleet-summary")!;
    expect(summary.textContent).toContain("running");
    expect(summary.textContent).toContain("succeeded");
    expect(summary.textContent).toContain("failed");
    expect(summary.textContent).toContain("waiting");
  });

  it("hides zero counts", () => {
    renderFleet();
    // stuck=0 and created=0 should not appear
    expect(screen.queryByText(/stuck/i)).not.toBeInTheDocument();
    // "created" with count 0 should not show
    expect(screen.queryByText(/created/i)).not.toBeInTheDocument();
  });

  it("renders progress bar segments", () => {
    const { container } = renderFleet();
    const bar = container.querySelector(".fleet-bar");
    expect(bar).toBeTruthy();
    const segments = bar!.querySelectorAll(".segment");
    // Segments for non-zero statuses: running(2), succeeded(1), failed(1), waiting(1) = 4 segments
    expect(segments.length).toBe(4);
  });

  it("renders children table with progress text", () => {
    renderFleet();
    // Children with progress show fraction
    expect(screen.getByText("3 / 10")).toBeInTheDocument();
    expect(screen.getByText("7 / 10")).toBeInTheDocument();
    expect(screen.getByText("10 / 10")).toBeInTheDocument();
  });

  it("renders children as links", () => {
    renderFleet();
    const link = screen.getByRole("link", { name: "1.0-dev.abc.pod1" });
    expect(link).toHaveAttribute("href", "/run/1.0-dev.abc.pod1");
  });

  it("shows a dash for children without progress", () => {
    renderFleet();
    // pod4 has null progress — should show a dash
    const rows = document.querySelectorAll(".fleet-children tbody tr");
    const lastRow = rows[rows.length - 1];
    expect(lastRow.textContent).toContain("—"); // em-dash
  });

  it("collapses children table when more than 10 rows", async () => {
    const bigFleet: Fleet = {
      expected: 12,
      counts: { running: 12 },
      children: Array.from({ length: 12 }, (_, i) => ({
        verstr: `1.0-dev.abc.pod${i}`,
        status: "running" as const,
        progress: i,
        progress_total: 10,
      })),
    };

    renderFleet(bigFleet);
    // Only first 10 rows visible initially
    const visibleRows = document.querySelectorAll(".fleet-children tbody tr");
    expect(visibleRows.length).toBe(10);

    // A toggle button should exist
    const toggle = screen.getByRole("button", { name: /show all/i });
    expect(toggle).toBeInTheDocument();

    // Clicking it reveals all rows
    fireEvent.click(toggle);
    const allRows = document.querySelectorAll(".fleet-children tbody tr");
    expect(allRows.length).toBe(12);
  });

  it("renders status pills for each child", () => {
    const { container } = renderFleet();
    const pills = container.querySelectorAll(".fleet-children .status-pill");
    expect(pills.length).toBe(4);
  });

  it("displays statuses in order: waiting, running, succeeded, failed", () => {
    const { container } = renderFleet();
    const summary = container.querySelector(".fleet-summary")!;
    const labels = Array.from(summary.querySelectorAll(".fleet-count"))
      .map((el) => el.textContent?.replace(/\d+/g, "").trim());
    expect(labels).toEqual(["waiting", "running", "succeeded", "failed"]);
  });
});
