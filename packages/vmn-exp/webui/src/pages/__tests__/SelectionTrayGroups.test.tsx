/** The tray with query groups (a job's "Select all N matching"): counted,
 *  listed as one removable entry each, archived by query, and compared
 *  through their top runs. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { renderWithClient } from "../../test-utils";

vi.mock("../../api", () => ({ api: { action: vi.fn(), actionPreview: vi.fn(), job: vi.fn() } }));

import { api } from "../../api";
import { readPicks, writePicks, type RunPick } from "../../util/runSelection";
import { addQueryGroup, readGroups, type QueryGroup } from "../../util/selectionGroups";
import SelectionTray from "../SelectionTray";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const PICKS: RunPick[] = [
  { verstr: "x1", job: "J2", name: "x1" },
  { verstr: "x2", job: "J3", name: "x2" },
];
const members = Array.from({ length: 12 }, (_, i) => ({ verstr: `m${i}`, job: "J1" }));
const GROUP: QueryGroup = {
  scope: "J1", q: "", status: "failed", count: 4000, job: "J1", label: "hist-0012", members,
};

function Where() {
  const loc = useLocation();
  return <output data-testid="where">{loc.pathname + loc.search}</output>;
}

function renderTray() {
  writePicks("w", "a", PICKS);
  addQueryGroup("w", "a", GROUP);
  addQueryGroup("w", "a", { ...GROUP, scope: "J4", job: "J4", label: "sweep-4", count: 10, members: [] });
  return renderWithClient(
    <MemoryRouter initialEntries={["/ws/w/app/a/tree"]}>
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

describe("the tray with query groups", () => {
  it("counts the explicit picks plus the groups' counts", () => {
    renderTray();
    expect(within(tray()).getByText("4,012", { selector: ".sel-badge" })).toBeInTheDocument();
    expect(within(tray()).getByRole("status")).toHaveTextContent("4,012 selected from 4 jobs");
  });

  it("lists a group as one removable entry", () => {
    renderTray();
    fireEvent.click(within(tray()).getByRole("button", { name: /from 4 jobs/ }));
    const list = screen.getByRole("list", { name: "Selected runs" });
    expect(within(list).getByText("all 4,000 matching in hist-0012 (status = failed)")).toBeInTheDocument();
    fireEvent.click(within(list).getByRole("button", {
      name: "Remove all 4,000 matching in hist-0012 (status = failed)",
    }));
    expect(readGroups("w", "a").map((g) => g.scope)).toEqual(["J4"]);
    expect(within(tray()).getByRole("status")).toHaveTextContent("12 selected from 3 jobs");
  });

  it("compares the explicit picks and the top 10 runs of each group, and says so", () => {
    renderTray();
    const compare = within(tray()).getByRole("button", { name: /^compare/i });
    expect(compare).toHaveAttribute("title", expect.stringMatching(/top 10 runs of each/i));
    fireEvent.click(compare);
    const url = new URL(where(), "http://x");
    expect(url.pathname).toBe("/ws/w/app/a/compare-runs");
    expect(url.searchParams.getAll("sel")).toEqual(["x1", "x2", ...members.slice(0, 10).map((p) => p.verstr)]);
  });

  it("archives each group by query and the explicit picks by verstr, after a counted confirm", async () => {
    m.actionPreview.mockImplementation((_w: string, _a: string, _act: string, body: { scope: string }) =>
      Promise.resolve({ count: body.scope === "J1" ? 3990 : 10, sample: [] }));
    m.action.mockResolvedValue({ id: "j", status: "running", command: [] });
    m.job.mockResolvedValue({ id: "j", status: "succeeded", command: [] });
    renderTray();
    fireEvent.click(within(tray()).getByRole("button", { name: "Archive" }));
    expect(await screen.findByRole("dialog")).toHaveTextContent("Archive 4,002 runs?");
    expect(m.actionPreview).toHaveBeenCalledWith("w", "a", "exp_archive", { scope: "J1", status: "failed" });
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(m.action).toHaveBeenCalledTimes(3), { timeout: 4000 });
    expect(m.action.mock.calls.map((c) => c[3])).toEqual([
      { scope: "J1", status: "failed" }, { scope: "J4", status: "failed" }, { verstrs: ["x1", "x2"] },
    ]);
    await waitFor(() => expect(readGroups("w", "a")).toEqual([]), { timeout: 4000 });
    expect(readPicks("w", "a")).toEqual([]);
  });

  it("clears the groups with the picks", () => {
    renderTray();
    fireEvent.click(within(tray()).getByRole("button", { name: "Clear selection" }));
    expect(readGroups("w", "a")).toEqual([]);
    expect(screen.queryByRole("region", { name: "Selection" })).toBeNull();
  });
});
