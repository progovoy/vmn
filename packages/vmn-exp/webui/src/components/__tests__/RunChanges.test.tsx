import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { useState } from "react";
import { renderWithClient } from "../../test-utils";

vi.mock("../../apiRunCode", () => ({ fetchRunPatch: vi.fn(), fetchRunBaselines: vi.fn() }));
vi.mock("../../api", () => ({
  api: { experimentsDiff: vi.fn() },
  appName: (tag: string) => tag.replaceAll("-", "/"),
}));

import { fetchRunBaselines, fetchRunPatch } from "../../apiRunCode";
import type { BaselineRun, RunBaselines } from "../../apiRunCode";
import { api } from "../../api";
import type { DiffDelta } from "../../types";
import RunChanges from "../RunChanges";

const baselinesMock = fetchRunBaselines as unknown as ReturnType<typeof vi.fn>;
const patchMock = fetchRunPatch as unknown as ReturnType<typeof vi.fn>;
const diffMock = api.experimentsDiff as unknown as ReturnType<typeof vi.fn>;

const RUN = "0.0.1-dev.run";
const run = (verstr: string, idx: number, name: string | null = null): BaselineRun =>
  ({ verstr, idx, name, status: "succeeded" });
const delta = (from: number, to: number, goal: "min" | "max" | null = "min", param = false): DiffDelta =>
  ({ from, to, goal, param });

const DIFF_TEXT = [
  "diff --git a/train.py b/train.py",
  "--- a/train.py",
  "+++ b/train.py",
  "@@ -1 +1,2 @@",
  "-lr = 0.1",
  "+lr = 0.01",
  "+seed = 1",
].join("\n");

function Harness({ initial = null }: { initial?: string | null }) {
  const [baseline, setBaseline] = useState<string | null>(initial);
  return <RunChanges ws="test" app="my-app" verstr={RUN} baseline={baseline} onBaseline={setBaseline} />;
}

function renderCard(baselines: RunBaselines, initial: string | null = null) {
  baselinesMock.mockResolvedValue(baselines);
  return renderWithClient(<MemoryRouter><Harness initial={initial} /></MemoryRouter>);
}

beforeEach(() => {
  vi.clearAllMocks();
  diffMock.mockResolvedValue({ from_verstr: "x", to_verstr: RUN, metrics_delta: {}, diff: DIFF_TEXT });
});

describe("RunChanges", () => {
  it("defaults to the run's own patch when it captured one", async () => {
    patchMock.mockResolvedValue({
      text: "=== working_tree ===\n" + DIFF_TEXT,
      files: [{ path: "train.py", added: 2, removed: 1 }],
    });
    renderCard({ base: run(RUN, 4), previous: run("v-prev", 3) });
    const card = await screen.findByRole("region", { name: "Changes" });
    expect(await within(card).findByText("train.py")).toBeInTheDocument();
    expect(within(card).getByText("+2")).toBeInTheDocument();
    expect(within(card).getByText("−1")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "base version" })).toHaveAttribute("aria-pressed", "true");
    expect(patchMock).toHaveBeenCalledWith("test", "my-app", RUN);
    expect(diffMock).not.toHaveBeenCalled();
  });

  it("defaults to the previous run for a clean tree and diffs it against this run", async () => {
    diffMock.mockResolvedValue({
      from_verstr: "v-prev", to_verstr: RUN, metrics_delta: {},
      diff: DIFF_TEXT.replace("a/train.py b/train.py", `a/v-prev/train.py b/${RUN}/train.py`),
    });
    renderCard({ previous: run("v-prev", 3, "prev"), best: run("v-best", 7) });
    expect(await screen.findByText("train.py")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "previous @3 prev" })).toHaveAttribute("aria-pressed", "true");
    expect(diffMock).toHaveBeenCalledWith("test", "my-app", "v-prev", RUN);
    expect(patchMock).not.toHaveBeenCalled();
  });

  it("refetches when the baseline is switched", async () => {
    renderCard({ previous: run("v-prev", 3), best: run("v-best", 7) });
    await waitFor(() => expect(diffMock).toHaveBeenCalledWith("test", "my-app", "v-prev", RUN));
    fireEvent.click(screen.getByRole("button", { name: "best @7" }));
    await waitFor(() => expect(diffMock).toHaveBeenCalledWith("test", "my-app", "v-best", RUN));
    expect(screen.getByRole("button", { name: "best @7" })).toHaveAttribute("aria-pressed", "true");
  });

  it("shows the top 5 goal metrics by |Δ|, the rest behind +N more, params apart", async () => {
    diffMock.mockResolvedValue({
      from_verstr: "v-prev", to_verstr: RUN, diff: "",
      metrics_delta: {
        a: delta(1, 1.1), b: delta(1, 5), c: delta(1, 3, "max"), d: delta(1, 2),
        e: delta(1, 1.5), f: delta(1, 1.2), plain: delta(1, 100, null),
        lr: delta(0.1, 0.01, null, true),
      },
    });
    renderCard({ previous: run("v-prev", 3) });
    const table = await screen.findByRole("table", { name: "Metric changes" });
    const names = () => within(table).getAllByRole("rowheader").map((c) => c.textContent);
    expect(names()).toEqual(["b", "c", "d", "e", "f"]);
    fireEvent.click(screen.getByRole("button", { name: "+2 more" }));
    expect(names()).toEqual(["b", "c", "d", "e", "f", "a", "plain"]);
    const params = screen.getByRole("region", { name: "Params changed" });
    expect(within(params).getByRole("heading")).toHaveTextContent(/params changed\s*1/i);
    const lr = within(params).getByRole("rowheader", { name: "lr" }).closest("tr")!;
    expect(within(lr).getAllByRole("cell").map((c) => c.textContent)).toEqual(["0.1", "0.01"]);
  });

  it("expands the unified diff on demand", async () => {
    renderCard({ previous: run("v-prev", 3) });
    const toggle = await screen.findByRole("button", { name: "Show diff" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("+seed = 1")).toBeNull();
    fireEvent.click(toggle);
    expect(screen.getByText("+seed = 1")).toHaveClass("add");
    expect(screen.getByRole("button", { name: "Hide diff" })).toHaveAttribute("aria-expanded", "true");
  });

  it("links to the Compare page's code tab for the pair", async () => {
    renderCard({ previous: run("v-prev", 3) });
    expect(await screen.findByRole("link", { name: "Open in Compare →" })).toHaveAttribute(
      "href", `/ws/test/app/my-app/compare-runs?tab=code&sel=v-prev&sel=${RUN}`,
    );
  });

  it("says in one line why there is nothing to show without code or baselines", async () => {
    renderCard({});
    expect(await screen.findByText(
      "No code changes captured (clean tree) and no earlier run to compare with.",
    )).toBeInTheDocument();
    expect(diffMock).not.toHaveBeenCalled();
  });

  it("gives the patch's reason when the run's code is gone", async () => {
    patchMock.mockResolvedValue({ text: null, reason: "code_missing", files: [] });
    renderCard({ base: run(RUN, 4) });
    expect(await screen.findByText(/code object is missing/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Show diff" })).toBeNull();
  });

  it("gives the diff's reason when a run's code can't be materialised", async () => {
    diffMock.mockRejectedValue(Object.assign(new Error("HTTP 422"), {
      status: 422, body: { reason: "no_code", detail: "x", verstr: "v-prev" },
    }));
    renderCard({ previous: run("v-prev", 3) });
    expect(await screen.findByText(/no captured code/)).toBeInTheDocument();
  });

  it("diffs against a requested run that is no baseline (the failure card's last good)", async () => {
    renderCard({ previous: run("v-prev", 3) }, "v-good");
    await waitFor(() => expect(diffMock).toHaveBeenCalledWith("test", "my-app", "v-good", RUN));
    expect(screen.getByRole("button", { name: "vs v-good" })).toHaveAttribute("aria-pressed", "true");
  });
});
