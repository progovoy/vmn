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
vi.mock("../../components/TrainingCurves", () => ({ default: () => null }));

import { api } from "../../api";
import { createQueryClient } from "../../queryClient";
import { rowsKey } from "../../queries";
import Run from "../Run";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const V = "0.0.2-rc.1";

function renderRun(client = createQueryClient()) {
  render(
    <QueryClientProvider client={client}>
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

describe("Run header name and tags", () => {
  it("titles the page with the run name, keeping the verstr beside it", async () => {
    m.experiment.mockResolvedValue({
      metadata: { verstr: V, name: "wide-resnet", tags: { team: "vision" } },
      metrics: {}, series: {}, patches: {},
    });
    renderRun();
    expect(await screen.findByRole("heading", { name: "wide-resnet" })).toBeInTheDocument();
    expect(screen.getByText(V)).toBeInTheDocument();
    expect(screen.getByText("team: vision")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "+ tag" })).toBeInTheDocument();
  });

  it("falls back to the verstr as the title", async () => {
    m.experiment.mockResolvedValue({ metadata: { verstr: V }, metrics: {}, series: {}, patches: {} });
    renderRun();
    expect(await screen.findByRole("heading", { name: V })).toBeInTheDocument();
  });

  it("paints name and tags from the cached leaderboard row", () => {
    m.experiment.mockImplementation(() => new Promise(() => {}));
    const client = createQueryClient();
    client.setQueryData(rowsKey("test", "my-app", {}), {
      rows: [{ idx: 1, verstr: V, code_verstr: V, timestamp: null, note: null, branch: null,
        base_version: null, user_meta: null, metrics: {}, name: "from-row", tags: { a: "b" } }],
      total: 1,
    });
    renderRun(client);
    expect(screen.getByRole("heading", { name: "from-row" })).toBeInTheDocument();
    expect(screen.getByText("a: b")).toBeInTheDocument();
  });
});
