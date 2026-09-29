import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { renderWithClient } from "../../test-utils";

vi.mock("../../apiRun", () => ({ runLineage: vi.fn() }));

import { runLineage } from "../../apiRun";
import type { Lineage, LineageNode } from "../../apiRun";
import RunLineage, { LineageView } from "../RunLineage";

const mockedLineage = runLineage as unknown as ReturnType<typeof vi.fn>;

function node(verstr: string, extra: Partial<LineageNode> = {}): LineageNode {
  return {
    app: "my/app", verstr, name: null, timestamp: null, status: "succeeded",
    depth: 1, found: true, links: [], ...extra,
  };
}

const LINEAGE: Lineage = {
  app: "my/app",
  verstr: "0.0.1-dev.train",
  upstream: [
    node("0.0.1-dev.prep", {
      name: "prep",
      links: [{ input: "data", artifact: "data.csv", digest: "sha256:ab", via: "digest" }],
    }),
    node("p1", { app: "root/feat" }),
    node("gone", { found: false, status: null }),
  ],
  downstream: [
    node("0.0.1-dev.eval", {
      depth: 2,
      links: [{ input: "model", artifact: "model.pkl", digest: null, via: "uri" }],
    }),
  ],
  models: [{ model: "clf", version: 3, aliases: ["prod"], status: "active", artifact_path: "model.pkl" }],
  truncated: false,
};

function renderView(lineage: Lineage) {
  return render(
    <MemoryRouter>
      <LineageView ws="test" lineage={lineage} />
    </MemoryRouter>,
  );
}

beforeEach(() => vi.clearAllMocks());

describe("LineageView", () => {
  it("shows each run's status as a status pill", () => {
    renderView(LINEAGE);
    const pills = screen.getAllByLabelText(/^succeeded/);
    expect(pills).toHaveLength(3);
    pills.forEach((p) => expect(p).toHaveClass("status-pill", "succeeded"));
  });

  it("links upstream and downstream runs to their run pages", () => {
    renderView(LINEAGE);
    expect(screen.getByRole("link", { name: "prep" })).toHaveAttribute(
      "href", "/ws/test/app/my-app/run/0.0.1-dev.prep",
    );
    expect(screen.getByRole("link", { name: "0.0.1-dev.eval" })).toHaveAttribute(
      "href", "/ws/test/app/my-app/run/0.0.1-dev.eval",
    );
    expect(screen.getByText("data ← data.csv (digest)")).toBeInTheDocument();
    expect(screen.getByText("model ← model.pkl (uri)")).toBeInTheDocument();
    expect(screen.getByText("depth 2")).toBeInTheDocument();
  });

  it("links a run of another app under that app and leaves a missing run unlinked", () => {
    renderView(LINEAGE);
    expect(screen.getByRole("link", { name: "root/feat:p1" })).toHaveAttribute(
      "href", "/ws/test/app/root-feat/run/p1",
    );
    expect(screen.queryByRole("link", { name: "gone" })).toBeNull();
    expect(screen.getByText("gone")).toBeInTheDocument();
    expect(screen.getByText("missing")).toBeInTheDocument();
  });

  it("links registered models", () => {
    renderView(LINEAGE);
    expect(screen.getByRole("link", { name: "clf v3" })).toHaveAttribute("href", "/ws/test/models/clf");
    expect(screen.getByText("prod")).toBeInTheDocument();
  });

  it("says so when nothing is linked", () => {
    renderView({ ...LINEAGE, upstream: [], downstream: [], models: [] });
    expect(screen.getByText(/no linked runs/i)).toBeInTheDocument();
  });

  it("flags a truncated answer", () => {
    renderView({ ...LINEAGE, truncated: true });
    expect(screen.getByText(/truncated/i)).toBeInTheDocument();
  });
});

describe("RunLineage", () => {
  it("fetches the lineage and refetches at a new depth", async () => {
    mockedLineage.mockResolvedValue(LINEAGE);
    renderWithClient(
      <MemoryRouter>
        <RunLineage ws="test" app="my-app" verstr="0.0.1-dev.train" />
      </MemoryRouter>,
    );
    expect(await screen.findByRole("link", { name: "prep" })).toBeInTheDocument();
    expect(mockedLineage).toHaveBeenCalledWith("test", "my-app", "0.0.1-dev.train", 1);
    fireEvent.change(screen.getByLabelText(/lineage depth/i), { target: { value: "3" } });
    await waitFor(() =>
      expect(mockedLineage).toHaveBeenCalledWith("test", "my-app", "0.0.1-dev.train", 3),
    );
  });

  it("shows the error when the request fails", async () => {
    mockedLineage.mockRejectedValue(new Error("boom"));
    renderWithClient(
      <MemoryRouter>
        <RunLineage ws="test" app="my-app" verstr="0.0.1-dev.train" />
      </MemoryRouter>,
    );
    expect(await screen.findByText(/boom/)).toBeInTheDocument();
  });
});
