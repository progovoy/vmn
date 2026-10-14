/** An explicit pick that a selected query also matches, but that the board
 *  never loaded, is counted once: the server says which picks the group's
 *  filter matches, the tray subtracts them and leaves them out of the
 *  verstr bodies. Until it answers, the count is an upper bound. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { renderWithClient } from "../../test-utils";

vi.mock("../../api", () => ({
  api: { action: vi.fn(), actionPreview: vi.fn(), job: vi.fn(), experimentsPaged: vi.fn() },
}));

import { api } from "../../api";
import { writePicks, type RunPick } from "../../util/runSelection";
import { addQueryGroup, type QueryGroup } from "../../util/selectionGroups";
import SelectionTray from "../SelectionTray";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const PICKS: RunPick[] = [
  { verstr: "p1", job: "J1" }, { verstr: "p2", job: "J1" }, { verstr: "x", job: "J2" },
];
const GROUP: QueryGroup = {
  scope: "J1", q: "loss < 1", status: "failed", count: 100, job: "J1", label: "grid", members: [],
};

function renderTray() {
  writePicks("w", "a", PICKS);
  addQueryGroup("w", "a", GROUP);
  return renderWithClient(<MemoryRouter><SelectionTray ws="w" app="a" /></MemoryRouter>);
}

const tray = () => screen.getByRole("region", { name: "Selection" });
const badge = () => tray().querySelector(".sel-badge")!;
const overlapOf = (verstrs: string[]) => ({ rows: verstrs.map((verstr) => ({ verstr })), total: verstrs.length });

beforeEach(() => {
  sessionStorage.clear();
  vi.clearAllMocks();
});

describe("the tray's picks inside a selected query", () => {
  it("asks the server which picks of the group's outer run its filter matches", async () => {
    m.experimentsPaged.mockResolvedValue(overlapOf(["p1"]));
    renderTray();
    await waitFor(() => expect(badge()).toHaveTextContent(/^102$/));
    expect(m.experimentsPaged).toHaveBeenCalledTimes(1);
    expect(m.experimentsPaged).toHaveBeenCalledWith("w", "a", {
      scope: "J1", query: '(loss < 1) and verstr in ("p1", "p2")', status: "failed", limit: 2,
    });
    expect(within(tray()).getByRole("status")).toHaveTextContent(/^102 selected from 2 /);
  });

  it("shows an upper bound until the server answers", async () => {
    let answer: (v: unknown) => void = () => {};
    m.experimentsPaged.mockReturnValue(new Promise((r) => { answer = r; }));
    renderTray();
    expect(badge()).toHaveTextContent("≤103");
    expect(within(tray()).getByRole("status")).toHaveTextContent(/^at most 103 selected from 2 /);
    await act(async () => answer(overlapOf(["p1", "p2"])));
    expect(badge()).toHaveTextContent(/^101$/);
  });

  it("keeps the known overlap while a new pick is being asked about", async () => {
    m.experimentsPaged.mockResolvedValueOnce(overlapOf(["p1"]));
    renderTray();
    await waitFor(() => expect(badge()).toHaveTextContent(/^102$/));
    m.experimentsPaged.mockReturnValue(new Promise(() => {}));
    act(() => writePicks("w", "a", [...PICKS, { verstr: "p3", job: "J1" }]));
    expect(badge()).toHaveTextContent("≤103");
  });

  it("asks nothing when no pick is under a selected query's outer run", () => {
    writePicks("w", "a", [{ verstr: "x", job: "J2" }]);
    addQueryGroup("w", "a", GROUP);
    renderWithClient(<MemoryRouter><SelectionTray ws="w" app="a" /></MemoryRouter>);
    expect(m.experimentsPaged).not.toHaveBeenCalled();
    expect(badge()).toHaveTextContent(/^101$/);
  });

  it("archives the overlapping picks once, through their group", async () => {
    m.experimentsPaged.mockResolvedValue(overlapOf(["p1"]));
    m.actionPreview.mockResolvedValue({ count: 99, sample: [] });
    m.action.mockResolvedValue({ id: "j", status: "running", command: [] });
    m.job.mockResolvedValue({ id: "j", status: "succeeded", command: [] });
    renderTray();
    fireEvent.click(within(tray()).getByRole("button", { name: "Archive" }));
    expect(await screen.findByRole("dialog")).toHaveTextContent("Archive 101 runs?");
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(m.action).toHaveBeenCalledTimes(2), { timeout: 4000 });
    expect(m.action.mock.calls.map((c) => c[3])).toEqual([
      { scope: "J1", q: "loss < 1", status: "failed" }, { verstrs: ["p2", "x"] },
    ]);
  });
});
