import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { renderWithClient } from "../../test-utils";

vi.mock("../../api", () => ({
  api: {
    experiments: vi.fn(),
    experimentsPaged: vi.fn(),
    recentExperiments: vi.fn(),
    experimentsDiff: vi.fn(),
    metricsSchema: vi.fn(),
    action: vi.fn(),
    job: vi.fn(),
  },
  appTag: (n: string) => n.replaceAll("/", "-"),
  appName: (t: string) => t.replaceAll("-", "/"),
}));

import { api } from "../../api";
import CommandPalette from "../CommandPalette";
import ArtifactsList from "../ArtifactsList";
import ErrorBoundary from "../ErrorBoundary";
import { useJob } from "../ui";
import Compare from "../../pages/Compare";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
});

describe("CommandPalette", () => {
  it("lists the newest runs from a bounded request, never the full list", async () => {
    m.recentExperiments.mockResolvedValue([
      { verstr: "newest-run", timestamp: "2026-01-03T00:00:00Z", note: null },
      { verstr: "older-run", timestamp: "2026-01-01T00:00:00Z", note: null },
    ]);
    renderWithClient(
      <MemoryRouter>
        <CommandPalette ws="w" app="app" workspaces={[]} apps={[]} onClose={() => {}} />
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByText("newest-run")).toBeInTheDocument());
    expect(m.recentExperiments).toHaveBeenCalledWith("w", "app", 20);
    expect(m.experiments).not.toHaveBeenCalled();
    const labels = screen.getAllByText(/-run$/).map((e) => e.textContent);
    expect(labels).toEqual(["newest-run", "older-run"]);
  });
});

describe("Compare run picker", () => {
  const diff = {
    from_verstr: "0.0.1-dev.a", to_verstr: "0.0.2-dev.b",
    metrics_delta: {}, diff: "",
  };

  it("searches the server as you type instead of loading every run", async () => {
    m.experimentsDiff.mockResolvedValue(diff);
    m.metricsSchema.mockResolvedValue({});
    m.recentExperiments.mockResolvedValue([]);
    m.experimentsPaged.mockResolvedValue({
      rows: [{ verstr: "0.0.9-dev.abc", idx: 9 }], total: 1,
    });
    renderWithClient(
      <MemoryRouter initialEntries={["/ws/w/app/app/compare?v=@1&to=latest"]}>
        <Routes>
          <Route path="/ws/:ws/app/:app/compare" element={<Compare />} />
        </Routes>
      </MemoryRouter>,
    );
    await waitFor(() => screen.getAllByRole("combobox"));
    expect(m.experiments).not.toHaveBeenCalled();

    fireEvent.change(screen.getAllByRole("combobox")[0], { target: { value: "abc" } });
    await waitFor(() =>
      expect(m.experimentsPaged).toHaveBeenCalledWith(
        "w", "app",
        expect.objectContaining({ limit: 20, query: 'verstr ~ "abc" or note ~ "abc"' }),
      ),
    );
  });
});

describe("ArtifactsList with a token", () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  it("downloads through fetch with the Authorization header", async () => {
    sessionStorage.setItem("vmn_token", "s3cret");
    const fetchMock = vi.fn(() =>
      Promise.resolve(new Response(new Blob(["x"]), { status: 200 }))
    );
    vi.stubGlobal("fetch", fetchMock);
    const createObjectURL = vi.fn(() => "blob:x");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL, revokeObjectURL }));

    render(
      <ArtifactsList
        artifacts={[{ name: "model.pt", size: 10 }]}
        downloadUrl={(f) => `/api/v1/x/artifacts/${f}`}
      />,
    );
    fireEvent.click(screen.getByText("model.pt"));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/v1/x/artifacts/model.pt");
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer s3cret");
    await waitFor(() => expect(createObjectURL).toHaveBeenCalled());
  });
});

describe("useJob", () => {
  afterEach(() => { vi.useRealTimers(); });

  it("stops polling and reports an error when the job request fails", async () => {
    vi.useFakeTimers();
    m.action.mockResolvedValue({ id: "j1", status: "running" });
    m.job.mockRejectedValue(Object.assign(new Error("Job not found"), { status: 404 }));
    const { result } = renderHook(() => useJob());
    await act(async () => { await result.current.run("w", "app", "stamp", {}); });
    await act(async () => { await vi.advanceTimersByTimeAsync(600); });
    expect(m.job).toHaveBeenCalledTimes(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    expect(m.job).toHaveBeenCalledTimes(1);
    expect(result.current.error).toMatch(/Job not found/);
  });
});

describe("ErrorBoundary", () => {
  it("shows the error instead of a blank page", () => {
    const Boom = () => { throw new Error("kaboom"); };
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    render(<ErrorBoundary><Boom /></ErrorBoundary>);
    expect(screen.getByText(/something went wrong/i)).toBeInTheDocument();
    expect(screen.getByText(/kaboom/)).toBeInTheDocument();
    spy.mockRestore();
  });
});
