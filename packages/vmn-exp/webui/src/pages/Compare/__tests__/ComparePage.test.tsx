import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { renderWithClient } from "../../../test-utils";

vi.mock("uplot", async () => await import("../../../components/__tests__/fakeUPlot"));
vi.mock("../../../api", () => ({
  api: {
    experiment: vi.fn(), experimentsDiff: vi.fn(), metricsSchema: vi.fn(),
    recentExperiments: vi.fn(), experimentsPaged: vi.fn(),
  },
  appName: (t: string) => t.replaceAll("-", "/"),
}));
vi.mock("../../../apiSeries", () => ({ fetchSeriesBatch: vi.fn(), fetchRunStatuses: vi.fn() }));

import { api } from "../../../api";
import { fetchRunStatuses, fetchSeriesBatch } from "../../../apiSeries";
import { enableCanvas, resetInstances } from "../../../components/__tests__/fakeUPlot";
import type { ExperimentDetail } from "../../../types";
import ComparePage from "../ComparePage";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const batch = fetchSeriesBatch as unknown as ReturnType<typeof vi.fn>;

const detail = (verstr: string, idx: number, loss: number): ExperimentDetail => ({
  metadata: { verstr }, idx, name: null, params: { lr: idx }, metrics: { loss },
  series: {}, patches: {},
});
const DETAILS: Record<string, ExperimentDetail> = {
  a: detail("a", 1, 0.3), b: detail("b", 2, 0.2), c: detail("c", 3, 0.1),
};

const loc = { search: "" };
function Probe() {
  loc.search = useLocation().search;
  return null;
}
const sel = () => new URLSearchParams(loc.search).getAll("sel");
const tab = () => new URLSearchParams(loc.search).get("tab");

function renderPage(search: string) {
  return renderWithClient(
    <MemoryRouter initialEntries={[`/ws/w/app/my-app/compare-runs${search}`]}>
      <Probe />
      <Routes><Route path="/ws/:ws/app/:app/compare-runs" element={<ComparePage />} /></Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  resetInstances();
  enableCanvas();
  m.experiment.mockImplementation((_w: string, _a: string, v: string) =>
    DETAILS[v] ? Promise.resolve(DETAILS[v]) : Promise.reject(Object.assign(new Error("not found"), { status: 404 })));
  m.experimentsDiff.mockImplementation((_w: string, _a: string, v: string, to: string) =>
    Promise.resolve({ from_verstr: v, to_verstr: to, metrics_delta: {}, diff: "diff --git a/x b/x\n+new\n-old" }));
  m.metricsSchema.mockResolvedValue({});
  m.recentExperiments.mockResolvedValue([]);
  m.experimentsPaged.mockResolvedValue({
    rows: [{ verstr: "a", idx: 1, name: "baseline" }, { verstr: "b", idx: 2 }], total: 2,
  });
  batch.mockImplementation((_w: string, _a: string, vs: string[]) => Promise.resolve({
    series: Object.fromEntries(vs.map((v) => [v, { loss: [{ step: 0, value: 1, ts: null }] }])), missing: [],
  }));
  (fetchRunStatuses as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({});
});

describe("Compare page tabs", () => {
  it("opens on the curves tab and fetches no run details for it", async () => {
    renderPage("?sel=a&sel=b");
    const curves = await screen.findByRole("tab", { name: "Curves" });
    expect(curves).toHaveAttribute("aria-selected", "true");
    await waitFor(() => expect(batch).toHaveBeenCalledWith("w", "my-app", ["a", "b"], null, 1000));
    expect(m.experiment).not.toHaveBeenCalled();
  });

  it("links every tab with the same selection", async () => {
    renderPage("?sel=a&sel=b&tab=table");
    for (const [name, id] of [["Curves", "curves"], ["Table", "table"], ["Code", "code"]]) {
      const href = (await screen.findByRole("tab", { name })).getAttribute("href")!;
      const q = new URLSearchParams(href.split("?")[1]);
      expect(href.startsWith("/ws/w/app/my-app/compare-runs?")).toBe(true);
      expect(q.getAll("sel")).toEqual(["a", "b"]);
      expect(q.get("tab")).toBe(id);
    }
    expect(screen.getByRole("tab", { name: "Table" })).toHaveAttribute("aria-selected", "true");
  });

  it("switches curves -> table -> code in one click each, keeping the selection", async () => {
    renderPage("?sel=a&sel=b&sel=c");
    fireEvent.click(await screen.findByRole("tab", { name: "Table" }));
    expect(await screen.findByText(/3 runs side by side/)).toBeInTheDocument();
    expect(tab()).toBe("table");
    expect(sel()).toEqual(["a", "b", "c"]);
    fireEvent.click(screen.getByRole("tab", { name: "Code" }));
    await waitFor(() => expect(m.experimentsDiff).toHaveBeenCalledWith("w", "my-app", "a", "b"));
    expect(tab()).toBe("code");
    expect(sel()).toEqual(["a", "b", "c"]);
  });
});

describe("Compare page selection chips", () => {
  it("names each selected run by @N and name, verstr in the title", async () => {
    renderPage("?sel=a&sel=b");
    const chips = await screen.findByRole("list", { name: "selected runs" });
    expect(await within(chips).findByText("@1 baseline")).toHaveAttribute("title", "a");
    expect(within(chips).getByText("@2")).toHaveAttribute("title", "b");
    expect(m.experimentsPaged).toHaveBeenCalledWith(
      "w", "my-app", expect.objectContaining({ query: 'verstr in ("a", "b")', archived: true }),
    );
  });

  it("removes a run from the selection, keeping the tab", async () => {
    renderPage("?sel=a&sel=b&sel=c&tab=table");
    fireEvent.click(await screen.findByRole("button", { name: "remove b" }));
    await waitFor(() => expect(sel()).toEqual(["a", "c"]));
    expect(tab()).toBe("table");
  });

  it("adds a run through a picker", async () => {
    renderPage("?sel=a&sel=b");
    expect(screen.queryByRole("combobox")).toBeNull();
    fireEvent.click(await screen.findByRole("button", { name: /add run/i }));
    const picker = await screen.findByRole("combobox");
    fireEvent.change(picker, { target: { value: "c" } });
    fireEvent.keyDown(picker, { key: "Enter" });
    await waitFor(() => expect(sel()).toEqual(["a", "b", "c"]));
  });

  it("marks a ref the table could not load as not found", async () => {
    renderPage("?sel=a&sel=gone&sel=b&tab=table");
    const chips = await screen.findByRole("list", { name: "selected runs" });
    expect(await within(chips).findByText(/not found/)).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "remove gone" })).toHaveLength(1);
  });
});

describe("Compare page code tab", () => {
  it("diffs the first run against the second when more are selected, with a picker for the other side", async () => {
    renderPage("?sel=a&sel=b&sel=c&tab=code");
    await waitFor(() => expect(m.experimentsDiff).toHaveBeenCalledWith("w", "my-app", "a", "b"));
    const [, toPicker] = await screen.findAllByRole("combobox");
    fireEvent.change(toPicker, { target: { value: "c" } });
    fireEvent.keyDown(toPicker, { key: "Enter" });
    await waitFor(() => expect(m.experimentsDiff).toHaveBeenCalledWith("w", "my-app", "a", "c"));
    expect(sel()).toEqual(["a", "b", "c"]);
  });

  it("with two selected, a picker change replaces that side of the selection", async () => {
    renderPage("?sel=a&sel=b&tab=code");
    const [fromPicker] = await screen.findAllByRole("combobox");
    fireEvent.change(fromPicker, { target: { value: "c" } });
    fireEvent.keyDown(fromPicker, { key: "Enter" });
    await waitFor(() => expect(sel()).toEqual(["c", "b"]));
  });

  it("renders the diff lines through the shared diff renderer", async () => {
    renderPage("?sel=a&sel=b&tab=code");
    expect(await screen.findByText("+new")).toHaveClass("add");
    expect(screen.getByText("-old")).toHaveClass("del");
  });

  it("keeps the K6 reason, both pickers and the CLI line on a 422", async () => {
    m.experimentsDiff.mockRejectedValue(Object.assign(new Error("Failed to materialize"), {
      status: 422, body: { reason: "code_missing", detail: "Failed to materialize", verstr: "a" },
    }));
    renderPage("?sel=a&sel=b&tab=code");
    expect(await screen.findByText(/code_missing/)).toBeInTheDocument();
    expect(screen.getAllByRole("combobox")).toHaveLength(2);
    expect(screen.getAllByText("vmn-exp diff my/app -v a -v b").length).toBeGreaterThan(0);
  });
});
