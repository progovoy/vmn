import { describe, it, expect, vi, afterEach } from "vitest";
import { act, render, renderHook, screen } from "@testing-library/react";

vi.mock("../../api", () => ({
  api: { action: vi.fn(), job: vi.fn() },
}));

import { api } from "../../api";
import { JobCard, useJob } from "../ui";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

describe("useJob on a 404 poll", () => {
  afterEach(() => { vi.useRealTimers(); });

  it("reads the job as unknown: polling stops, no error, onDone not called", async () => {
    vi.useFakeTimers();
    m.action.mockResolvedValue({
      id: "j1", command: [], status: "running", exit_code: null, log: "started",
    });
    m.job.mockRejectedValue(Object.assign(new Error("Job not found"), { status: 404 }));
    const onDone = vi.fn();
    const { result } = renderHook(() => useJob(onDone));
    await act(async () => { await result.current.run("w", "app", "stamp", {}); });
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });

    expect(m.job).toHaveBeenCalledTimes(1);
    expect(result.current.error).toBeNull();
    expect(onDone).not.toHaveBeenCalled();
    expect(result.current.job?.status).toBe("unknown");

    render(<JobCard job={result.current.job!} />);
    expect(screen.getByText(/status unknown/)).toBeInTheDocument();
    expect(screen.getByText(/Reload to see the result/)).toBeInTheDocument();
    expect(screen.getByText("started")).toBeInTheDocument();
    expect(screen.queryByText(/Job not found/)).not.toBeInTheDocument();
  });
});
