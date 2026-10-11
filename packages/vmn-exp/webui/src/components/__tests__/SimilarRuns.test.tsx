import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { renderWithClient } from "../../test-utils";

vi.mock("../../apiSimilar", () => ({ runSimilar: vi.fn(), textSimilar: vi.fn() }));

import { runSimilar } from "../../apiSimilar";
import type { SimilarItem } from "../../apiSimilar";
import SimilarRuns, { SimilarList } from "../SimilarRuns";

const mockedSimilar = runSimilar as unknown as ReturnType<typeof vi.fn>;
const HOUR_AGO = new Date(Date.now() - 3 * 3600_000).toISOString();

function item(verstr: string, extra: Partial<SimilarItem> = {}): SimilarItem {
  return {
    workspace: "test", app: "my/app", verstr, name: null, score: 0.8731,
    reasons: [], signals: {}, group_size: 1, goal: null, author: null,
    timestamp: null, status: "succeeded", note: null, intent: null, ...extra,
  };
}

const TWIN = item("0.0.1-dev.twin", {
  name: "twin", author: "bob@x.io", timestamp: HOUR_AGO, group_size: 3,
  reasons: ["2 shared functions: loss.py::focal_loss", "lr 1e-4 vs 3e-4"],
  goal: { metric: "loss", goal: "min", value: 0.3 },
  intent: { text: "Focal loss for class imbalance", keywords: ["focal loss"], truncated: false },
});

function renderList(items: SimilarItem[], truncated = false) {
  return render(
    <MemoryRouter>
      <SimilarList items={items} ownApp="my/app" truncated={truncated} />
    </MemoryRouter>,
  );
}

beforeEach(() => vi.clearAllMocks());

describe("SimilarList", () => {
  it("links each run to its run page, another app's under that app", () => {
    renderList([TWIN, item("p1", { app: "root/feat", workspace: "other" })]);
    expect(screen.getByRole("link", { name: "twin" })).toHaveAttribute(
      "href", "/ws/test/app/my-app/run/0.0.1-dev.twin",
    );
    expect(screen.getByRole("link", { name: "root/feat:p1" })).toHaveAttribute(
      "href", "/ws/other/app/root-feat/run/p1",
    );
  });

  it("shows score, status, goal metric, author, age and the group's other runs", () => {
    renderList([TWIN]);
    const row = screen.getByRole("listitem");
    expect(within(row).getByText("0.87")).toBeInTheDocument();
    expect(within(row).getByLabelText(/^succeeded/)).toHaveClass("status-pill");
    expect(within(row).getByText("loss=0.3")).toBeInTheDocument();
    expect(within(row).getByText("bob@x.io")).toBeInTheDocument();
    expect(within(row).getByText("3h ago")).toBeInTheDocument();
    expect(within(row).getByText("(+2 runs)")).toBeInTheDocument();
  });

  it("shows the reasons as chips", () => {
    renderList([TWIN]);
    const chip = screen.getByText("2 shared functions: loss.py::focal_loss");
    expect(chip).toHaveClass("tag-chip");
    expect(screen.getByText("lr 1e-4 vs 3e-4")).toHaveClass("tag-chip");
  });

  it("keeps the intent collapsed until opened", () => {
    renderList([TWIN]);
    const details = screen.getByText("intent").closest("details")!;
    expect(details).not.toHaveAttribute("open");
    expect(within(details).getByText("Focal loss for class imbalance")).toBeInTheDocument();
    expect(within(details).getByText("focal loss")).toBeInTheDocument();
  });

  it("leaves out what a run does not have", () => {
    renderList([item("bare")]);
    expect(screen.queryByText("intent")).toBeNull();
    expect(screen.queryByText(/\+\d+ runs/)).toBeNull();
    expect(screen.getByRole("link", { name: "bare" })).toBeInTheDocument();
  });

  it("says so when nothing is similar, and when more matched", () => {
    renderList([]);
    expect(screen.getByText(/no similar runs/i)).toBeInTheDocument();
    renderList([TWIN], true);
    expect(screen.getByText(/more similar runs than shown/i)).toBeInTheDocument();
  });
});

describe("SimilarRuns", () => {
  const renderPanel = () => renderWithClient(
    <MemoryRouter>
      <SimilarRuns ws="test" app="my-app" verstr="0.0.1-dev.target" />
    </MemoryRouter>,
  );

  it("fetches this app's similar runs, then every app's on demand", async () => {
    mockedSimilar.mockResolvedValue({ items: [TWIN], truncated: false });
    renderPanel();
    expect(await screen.findByRole("link", { name: "twin" })).toBeInTheDocument();
    expect(mockedSimilar).toHaveBeenCalledWith("test", "my-app", "0.0.1-dev.target", { allApps: false });
    fireEvent.change(screen.getByLabelText(/similar runs scope/i), { target: { value: "all" } });
    await waitFor(() => expect(mockedSimilar).toHaveBeenCalledWith(
      "test", "my-app", "0.0.1-dev.target", { allApps: true },
    ));
  });

  it("shows the error when the request fails", async () => {
    mockedSimilar.mockRejectedValue(new Error("boom"));
    renderPanel();
    expect(await screen.findByText(/boom/)).toBeInTheDocument();
  });
});
