import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";

vi.mock("../../api", () => ({
  api: { experiment: vi.fn(), metricsSchema: vi.fn(), action: vi.fn(), job: vi.fn() },
  appName: (tag: string) => tag.replaceAll("-", "/"),
  appTag: (n: string) => n.replaceAll("/", "-"),
  artifactUrl: () => "/x",
}));
const curves = vi.fn();
vi.mock("../../components/TrainingCurves", () => ({
  default: (props: { markStep?: number | null }) => {
    curves(props.markStep);
    return null;
  },
}));

import { api } from "../../api";
import { createQueryClient } from "../../queryClient";
import Run from "../Run";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const V = "0.0.2-dev.fork";
const SRC = "0.0.2-dev.src";

function renderRun() {
  render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={[`/ws/test/app/my-app/run/${V}`]}>
        <Routes><Route path="/ws/:ws/app/:app/run/:verstr" element={<Run />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  m.metricsSchema.mockResolvedValue({});
});

describe("Run page of a forked run", () => {
  it("links the source run and marks the fork step on the charts", async () => {
    m.experiment.mockResolvedValue({
      metadata: { verstr: V }, metrics: {}, series: {}, patches: {},
      forked_from: { verstr: SRC, step: 200 }, rewinds: [],
    });
    renderRun();
    const link = await screen.findByRole("link", { name: SRC });
    expect(link).toHaveAttribute("href", `/ws/test/app/my-app/run/${SRC}`);
    expect(screen.getByTestId("fork-origin").textContent).toContain("@ step 200");
    expect(curves).toHaveBeenLastCalledWith(200);
  });

  it("shows nothing extra for a plain run", async () => {
    m.experiment.mockResolvedValue({ metadata: { verstr: V }, metrics: {}, series: {}, patches: {} });
    renderRun();
    await screen.findByRole("heading", { name: V });
    expect(screen.queryByTestId("fork-origin")).toBeNull();
  });
});
