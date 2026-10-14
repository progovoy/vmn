/** The app-wide selection tray: on every page of an app while runs are
 *  picked, `7 runs from 3 jobs · Compare · Archive · Clear`, expandable to
 *  the picks grouped by job. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, fireEvent, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { renderWithClient } from "../../test-utils";

vi.mock("../../api", () => ({ api: { action: vi.fn(), job: vi.fn() } }));

import { api } from "../../api";
import { readPicks, writePicks, type RunPick } from "../../util/runSelection";
import SelectionTray from "../SelectionTray";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const PICKS: RunPick[] = [
  { verstr: "J1", job: "J1", name: "grid", idx: 3 },
  { verstr: "t1", job: "J1", name: "trial-1", idx: 4 },
  { verstr: "t9", job: "J2", idx: 9 },
  { verstr: "solo", job: null, name: "solo" },
];

function Where() {
  const loc = useLocation();
  return <output data-testid="where">{loc.pathname + loc.search}</output>;
}

function renderTray(picks: RunPick[] = PICKS) {
  writePicks("w", "a", picks);
  return renderWithClient(
    <MemoryRouter initialEntries={["/ws/w/app/a/run/t1"]}>
      <Routes><Route path="*" element={<><SelectionTray ws="w" app="a" /><Where /></>} /></Routes>
    </MemoryRouter>,
  );
}

const tray = () => screen.getByRole("region", { name: "Selection" });
const where = () => screen.getByTestId("where").textContent!;

beforeEach(() => {
  sessionStorage.clear();
  vi.clearAllMocks();
});

describe("the selection tray", () => {
  it("is hidden when nothing is selected", () => {
    renderTray([]);
    expect(screen.queryByRole("region", { name: "Selection" })).toBeNull();
  });

  it("says how many runs from how many jobs", () => {
    renderTray();
    expect(within(tray()).getByText("4", { selector: ".sel-badge" })).toBeInTheDocument();
    expect(within(tray()).getByRole("button", { name: /from 2 outer runs/ })).toBeInTheDocument();
  });

  it("announces the count and its jobs in a status region", () => {
    renderTray();
    expect(within(tray()).getByRole("status")).toHaveTextContent("4 selected from 2 outer runs");
  });

  it("follows the store as another page changes it", () => {
    renderTray();
    act(() => writePicks("w", "a", PICKS.slice(0, 2)));
    expect(within(tray()).getByRole("status")).toHaveTextContent("2 selected from 1 outer run");
  });

  it("compares every pick", () => {
    renderTray();
    fireEvent.click(within(tray()).getByRole("button", { name: /^compare/i }));
    const url = new URL(where(), "http://x");
    expect(url.pathname).toBe("/ws/w/app/a/compare-runs");
    expect(url.searchParams.getAll("sel")).toEqual(["J1", "t1", "t9", "solo"]);
  });

  it("archives the picks after a confirm, then clears them", async () => {
    m.action.mockResolvedValue({ id: "j", status: "running", command: [] });
    m.job.mockResolvedValue({ id: "j", status: "succeeded", command: [] });
    renderTray();
    fireEvent.click(within(tray()).getByRole("button", { name: "Archive" }));
    expect(screen.getByRole("dialog")).toHaveTextContent("Archive 4 runs?");
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(m.action).toHaveBeenCalledWith("w", "a", "exp_archive", { verstrs: ["J1", "t1", "t9", "solo"] });
    await vi.waitFor(() => expect(readPicks("w", "a")).toEqual([]), { timeout: 3000 });
  });

  it("clears with its clear button", () => {
    renderTray();
    fireEvent.click(within(tray()).getByRole("button", { name: "Clear selection" }));
    expect(readPicks("w", "a")).toEqual([]);
    expect(screen.queryByRole("region", { name: "Selection" })).toBeNull();
  });

  it("is not cleared by Escape on a page without a board", () => {
    renderTray();
    fireEvent.keyDown(document.body, { key: "Escape" });
    expect(readPicks("w", "a")).toHaveLength(4);
  });
});

describe("the expanded tray", () => {
  const expand = () => fireEvent.click(within(tray()).getByRole("button", { name: /from 2 outer runs/ }));
  const list = () => screen.getByRole("list", { name: "Selected runs" });

  it("starts closed", () => {
    renderTray();
    expect(within(tray()).getByRole("button", { name: /from 2 outer runs/ })).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("list", { name: "Selected runs" })).toBeNull();
  });

  it("lists the picks grouped by job, linked to their run pages", () => {
    renderTray();
    expand();
    expect(within(tray()).getByRole("button", { name: /from 2 outer runs/ })).toHaveAttribute("aria-expanded", "true");
    const groups = within(list()).getAllByRole("group");
    expect(groups.map((g) => g.getAttribute("aria-label"))).toEqual(["grid", "J2", "Runs outside an outer run"]);
    expect(within(groups[0]).getByRole("link", { name: "trial-1" })).toHaveAttribute("href", "/ws/w/app/a/run/t1");
    expect(within(groups[1]).getByRole("link", { name: "@9" })).toHaveAttribute("href", "/ws/w/app/a/run/t9");
  });

  it("removes one pick", () => {
    renderTray();
    expand();
    fireEvent.click(within(list()).getByRole("button", { name: "Remove trial-1" }));
    expect(readPicks("w", "a").map((p) => p.verstr)).toEqual(["J1", "t9", "solo"]);
    expect(within(list()).queryByRole("link", { name: "trial-1" })).toBeNull();
  });
});
