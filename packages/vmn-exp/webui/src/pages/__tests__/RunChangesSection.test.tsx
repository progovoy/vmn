import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { renderWithClient } from "../../test-utils";

vi.mock("../../api", () => ({
  api: { experiment: vi.fn(), metricsSchema: vi.fn(), meta: vi.fn(), experimentsDiff: vi.fn() },
  appName: (tag: string) => tag.replaceAll("-", "/"),
  artifactUrl: () => "",
}));
vi.mock("../../apiRun", () => ({ runLineage: vi.fn(), runLog: vi.fn() }));
vi.mock("../../apiSimilar", () => ({ runSimilar: vi.fn(), textSimilar: vi.fn() }));
vi.mock("../../apiRunCode", () => ({ fetchRunPatch: vi.fn(), fetchRunBaselines: vi.fn() }));

import { api } from "../../api";
import { fetchRunBaselines } from "../../apiRunCode";
import Run from "../Run";

const mockedApi = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const RUN = "0.0.1-dev.eval";
const run = (verstr: string, idx: number) => ({ verstr, idx, name: null, status: "succeeded" });

function Search() {
  return <output data-testid="search">{useLocation().search}</output>;
}

function renderRun(entry: string) {
  return renderWithClient(
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route path="/ws/:ws/app/:app/run/:verstr" element={<><Run /><Search /></>} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mockedApi.experiment.mockResolvedValue({
    metadata: { verstr: RUN, timestamp: "2026-01-01T12:00:00Z", note: "" },
    metrics: {}, series: {}, log: [], patches: {},
  });
  mockedApi.metricsSchema.mockResolvedValue({});
  mockedApi.experimentsDiff.mockResolvedValue({ from_verstr: "v-prev", to_verstr: RUN, metrics_delta: {}, diff: "" });
  (fetchRunBaselines as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
    previous: run("v-prev", 3), best: run("v-best", 7),
  });
});

describe("Run page Changes card", () => {
  it("renders in a read-only workspace", async () => {
    mockedApi.meta.mockResolvedValue({ read_only: true });
    renderRun(`/ws/test/app/my-app/run/${RUN}`);
    expect(await screen.findByRole("region", { name: "Changes" })).toHaveAttribute("id", "changes");
    await waitFor(() => expect(mockedApi.experimentsDiff).toHaveBeenCalledWith("test", "my-app", "v-prev", RUN));
  });

  it("takes its baseline from ?baseline= and writes a switch back to it", async () => {
    mockedApi.meta.mockResolvedValue({ read_only: false });
    renderRun(`/ws/test/app/my-app/run/${RUN}?baseline=v-good`);
    await waitFor(() => expect(mockedApi.experimentsDiff).toHaveBeenCalledWith("test", "my-app", "v-good", RUN));
    fireEvent.click(await screen.findByRole("button", { name: "best @7" }));
    expect(screen.getByTestId("search")).toHaveTextContent("?baseline=best");
  });
});
