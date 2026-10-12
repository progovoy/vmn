import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { renderWithClient } from "../../test-utils";

vi.mock("../../api", () => ({
  api: {
    experiment: vi.fn(), metricsSchema: vi.fn(), facets: vi.fn(),
    meta: () => Promise.resolve({ version: "1" }), workspaces: () => Promise.resolve([]),
  },
  appName: (tag: string) => tag.replaceAll("-", "/"),
  artifactUrl: () => "",
}));

import { api } from "../../api";
import Run from "../Run";

const mocked = api as unknown as Record<"experiment" | "metricsSchema" | "facets", ReturnType<typeof vi.fn>>;
const httpError = (status: number, detail: string) =>
  Object.assign(new Error(detail), { status, body: { detail } });

function renderRun(ref: string) {
  return renderWithClient(
    <MemoryRouter initialEntries={[`/ws/ml-repo/app/ml_app/run/${encodeURIComponent(ref)}`]}>
      <Routes><Route path="/ws/:ws/app/:app/run/:verstr" element={<Run />} /></Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mocked.metricsSchema.mockResolvedValue({});
  mocked.facets.mockResolvedValue({ branches: [], metric_keys: [], param_keys: [], total: 53 });
});

describe("Run page for a missing run", () => {
  it("gives an @N past the end the app's range", async () => {
    mocked.experiment.mockRejectedValue(httpError(404, "Experiment @540 not found"));
    renderRun("@540");
    expect(await screen.findByRole("heading", { name: "No run @540 in ml_app" })).toBeInTheDocument();
    expect(await screen.findByText("ml_app has 53 runs (@1–@53).")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to experiments" }).getAttribute("href"))
      .toBe("/ws/ml-repo/app/ml_app");
  });

  it("suggests a pruned or unpushed run for a verstr, and searches for it", async () => {
    mocked.experiment.mockRejectedValue(httpError(404, "Experiment 0.2.0.dev3 not found"));
    renderRun("0.2.0.dev3");
    expect(await screen.findByText(/It may have been pruned/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Search runs for 0.2.0.dev3" })).toBeInTheDocument();
  });

  it("treats an invalid version as a missing run", async () => {
    mocked.experiment.mockRejectedValue(httpError(400, "Invalid version: ???"));
    renderRun("???");
    expect(await screen.findByRole("heading", { name: /^No run/ })).toBeInTheDocument();
  });

  it("keeps the error card for any other 404", async () => {
    mocked.experiment.mockRejectedValue(httpError(404, "Workspace ml-repo not found"));
    const { container } = renderRun("@3");
    await screen.findByText(/Workspace ml-repo not found/);
    expect(container.querySelector(".error")).not.toBeNull();
    expect(screen.queryByRole("heading", { name: /^No run/ })).toBeNull();
  });
});
