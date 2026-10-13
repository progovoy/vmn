/** Plan 23 W5: the job's Failures tab, its runs clustered by signature. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { renderWithClient } from "../../../test-utils";

vi.mock("../../../api", () => ({
  api: { experiment: vi.fn() },
  appName: (tag: string) => tag.replaceAll("-", "/"),
  appTag: (n: string) => n.replaceAll("/", "-"),
}));
vi.mock("../../../apiJob", () => ({ jobSummary: vi.fn(), jobFailures: vi.fn(), jobImportance: vi.fn() }));

import { api } from "../../../api";
import { jobFailures } from "../../../apiJob";
import JobFailures from "../JobFailures";
import { failuresFixture, JOB } from "./jobFixture";

const BASE = "/ws/test/app/my-app";
const experiment = api.experiment as unknown as ReturnType<typeof vi.fn>;

function renderFailures() {
  return renderWithClient(<MemoryRouter><JobFailures ws="test" app="my-app" verstr={JOB} /></MemoryRouter>);
}

const cluster = (label: string) => screen.getByRole("listitem", { name: new RegExp(label) });

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(jobFailures).mockResolvedValue(failuresFixture());
  experiment.mockResolvedValue({
    metadata: { verstr: "0.0.2-dev.t44" }, metrics: {}, series: {}, log: [], patches: {},
    output_tail: { lines: ["Traceback", "RuntimeError: CUDA out of memory"], truncated: true },
  });
});

describe("job failures", () => {
  it("lists each cluster with its count, share, time span, hosts and params", async () => {
    renderFailures();
    await screen.findByText("CUDA out of memory");
    expect(screen.getByText("3 failed runs in 2 clusters")).toBeInTheDocument();
    const c = cluster("CUDA out of memory");
    expect(within(c).getByText("2 runs")).toBeInTheDocument();
    expect(within(c).getByRole("meter", { name: "share of failures" })).toHaveAttribute("aria-valuenow", "67");
    expect(within(c).getByText("gpu-3 (2)")).toBeInTheDocument();
    expect(within(c).getByText("batch_size = 512 · 94% vs 25%")).toBeInTheDocument();
    expect(within(c).getByText(/first seen/)).toBeInTheDocument();
    expect(within(c).getByRole("link", { name: "0.0.2-dev.t44" })).toHaveAttribute("href", `${BASE}/run/0.0.2-dev.t44`);
  });

  it("filters the Runs tab to a cluster", async () => {
    renderFailures();
    await screen.findByText("CUDA out of memory");
    const link = within(cluster("CUDA out of memory")).getByRole("link", { name: "Show these runs" });
    const url = new URL(link.getAttribute("href")!, "http://x");
    expect(url.pathname).toBe(`${BASE}/run/${JOB}`);
    expect(url.searchParams.get("tab")).toBe("runs");
    expect(url.searchParams.get("q")).toBe('failure_sig = "failed | msg=CUDA out of memory. Tried to allocate <n> GiB"');
  });

  it("copies the example's rerun command", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    renderFailures();
    await screen.findByText("CUDA out of memory");
    fireEvent.click(within(cluster("CUDA out of memory")).getByRole("button", { name: /Copy rerun command/ }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("vmn-exp rerun my/app -v 0.0.2-dev.t44"));
  });

  it("loads the example's output tail only when expanded", async () => {
    renderFailures();
    await screen.findByText("CUDA out of memory");
    expect(experiment).not.toHaveBeenCalled();
    const c = cluster("CUDA out of memory");
    fireEvent.click(within(c).getByRole("button", { name: "Show output tail" }));
    expect(await within(c).findByText(/RuntimeError: CUDA out of memory/)).toBeInTheDocument();
    expect(experiment).toHaveBeenCalledWith("test", "my-app", "0.0.2-dev.t44");
    expect(within(c).getByRole("button", { name: "Hide output tail" })).toHaveAttribute("aria-expanded", "true");
  });

  it("is a positive empty state when nothing failed", async () => {
    vi.mocked(jobFailures).mockResolvedValue({ total_failed: 0, clusters: [] });
    renderFailures();
    expect(await screen.findByText("No failures. Every finished run succeeded.")).toBeInTheDocument();
  });

  it("shows an error it can retry", async () => {
    vi.mocked(jobFailures).mockRejectedValueOnce(new Error("boom"));
    renderFailures();
    expect(await screen.findByRole("alert")).toHaveTextContent("boom");
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("CUDA out of memory")).toBeInTheDocument();
  });
});
