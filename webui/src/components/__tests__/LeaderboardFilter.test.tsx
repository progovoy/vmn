import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import LeaderboardFilter from "../LeaderboardFilter";
import type { ExperimentRow } from "../../types";

const ROWS: ExperimentRow[] = [
  { idx: 1, verstr: "1.0.0-dev.aaa", code_verstr: "1.0.0-dev.aaa", timestamp: null, note: "batch size 64", branch: "main", base_version: "1.0.0", user_meta: null, metrics: { loss: 0.5 } },
  { idx: 2, verstr: "1.0.0-dev.bbb", code_verstr: "1.0.0-dev.bbb", timestamp: null, note: "learning rate 0.01", branch: "main", base_version: "1.0.0", user_meta: null, metrics: { loss: 0.3 } },
  { idx: 3, verstr: "1.0.0-dev.ccc", code_verstr: "1.0.0-dev.ccc", timestamp: null, note: "new optimizer", branch: "feat/optim", base_version: "1.0.0", user_meta: null, metrics: { loss: 0.2 } },
];

describe("LeaderboardFilter", () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); });

  it("renders search input and branch dropdown", () => {
    render(<LeaderboardFilter rows={ROWS} onFilter={() => {}} />);
    expect(screen.getByPlaceholderText(/search/i)).toBeInTheDocument();
    expect(screen.getByRole("combobox")).toBeInTheDocument();
  });

  it("text search filters by note", () => {
    const onFilter = vi.fn();
    render(<LeaderboardFilter rows={ROWS} onFilter={onFilter} />);
    fireEvent.change(screen.getByPlaceholderText(/search/i), { target: { value: "batch" } });
    act(() => { vi.advanceTimersByTime(200); });
    expect(onFilter).toHaveBeenCalled();
    const filtered = onFilter.mock.calls[onFilter.mock.calls.length - 1][0] as ExperimentRow[];
    expect(filtered).toHaveLength(1);
    expect(filtered[0].note).toBe("batch size 64");
  });

  it("text search filters by verstr", () => {
    const onFilter = vi.fn();
    render(<LeaderboardFilter rows={ROWS} onFilter={onFilter} />);
    fireEvent.change(screen.getByPlaceholderText(/search/i), { target: { value: "bbb" } });
    act(() => { vi.advanceTimersByTime(200); });
    const filtered = onFilter.mock.calls[onFilter.mock.calls.length - 1][0] as ExperimentRow[];
    expect(filtered).toHaveLength(1);
    expect(filtered[0].verstr).toContain("bbb");
  });

  it("branch dropdown filters by branch", () => {
    const onFilter = vi.fn();
    render(<LeaderboardFilter rows={ROWS} onFilter={onFilter} />);
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "feat/optim" } });
    const filtered = onFilter.mock.calls[onFilter.mock.calls.length - 1][0] as ExperimentRow[];
    expect(filtered).toHaveLength(1);
    expect(filtered[0].branch).toBe("feat/optim");
  });

  it("shows unique branches in dropdown", () => {
    render(<LeaderboardFilter rows={ROWS} onFilter={() => {}} />);
    const options = screen.getByRole("combobox").querySelectorAll("option");
    expect(options.length).toBe(3);
  });

  it("clear button resets all filters", () => {
    const onFilter = vi.fn();
    render(<LeaderboardFilter rows={ROWS} onFilter={onFilter} />);
    fireEvent.change(screen.getByPlaceholderText(/search/i), { target: { value: "batch" } });
    act(() => { vi.advanceTimersByTime(200); });
    fireEvent.click(screen.getByTitle(/clear/i));
    act(() => { vi.advanceTimersByTime(200); });
    const lastCall = onFilter.mock.calls[onFilter.mock.calls.length - 1][0] as ExperimentRow[];
    expect(lastCall).toHaveLength(3);
  });
});

const STATUS_ROWS: ExperimentRow[] = [
  { ...ROWS[0], status: "running" },
  { ...ROWS[1], status: "stuck" },
  { ...ROWS[2], status: "succeeded" },
];

describe("LeaderboardFilter status toggles", () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); });

  const last = (onFilter: ReturnType<typeof vi.fn>) =>
    onFilter.mock.calls[onFilter.mock.calls.length - 1][0] as ExperimentRow[];

  const ALL_STATUSES = ["running", "stuck", "failed", "succeeded", "created"];

  it("offers every status regardless of what the rows carry", () => {
    render(<LeaderboardFilter rows={ROWS} onFilter={() => {}} />);
    ALL_STATUSES.forEach((s) =>
      expect(screen.getByRole("button", { name: s })).toBeInTheDocument()
    );
  });

  it("keeps every toggle available once the server filtered the rows", () => {
    // The list endpoint answers a ?status= filter, so the rows coming back
    // only carry the picked status — the toggles must not shrink with them.
    const { rerender } = render(
      <LeaderboardFilter rows={STATUS_ROWS} onFilter={() => {}} />
    );
    fireEvent.click(screen.getByRole("button", { name: "running" }));
    rerender(
      <LeaderboardFilter rows={[STATUS_ROWS[0]]} onFilter={() => {}} />
    );
    ALL_STATUSES.forEach((s) =>
      expect(screen.getByRole("button", { name: s })).toBeInTheDocument()
    );
    expect(screen.getByRole("button", { name: "stuck" }))
      .toHaveAttribute("aria-pressed", "false");
  });

  it("leaves row filtering to the server", () => {
    const onFilter = vi.fn();
    render(<LeaderboardFilter rows={STATUS_ROWS} onFilter={onFilter} />);
    fireEvent.click(screen.getByRole("button", { name: "running" }));
    expect(last(onFilter)).toHaveLength(3);
  });

  it("marks a picked status as pressed and reports the CSV in display order", () => {
    const onStatusChange = vi.fn();
    render(
      <LeaderboardFilter
        rows={STATUS_ROWS}
        onFilter={() => {}}
        onStatusChange={onStatusChange}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: "stuck" }));
    fireEvent.click(screen.getByRole("button", { name: "running" }));
    expect(screen.getByRole("button", { name: "running" }))
      .toHaveAttribute("aria-pressed", "true");
    expect(onStatusChange).toHaveBeenLastCalledWith("running,stuck");
  });

  it("reports each status change exactly once", () => {
    const onStatusChange = vi.fn();
    render(
      <LeaderboardFilter
        rows={STATUS_ROWS}
        onFilter={() => {}}
        onStatusChange={onStatusChange}
      />
    );
    onStatusChange.mockClear();
    fireEvent.click(screen.getByRole("button", { name: "running" }));
    expect(onStatusChange).toHaveBeenCalledTimes(1);
  });

  it("clear resets the status toggles too", () => {
    const onStatusChange = vi.fn();
    render(
      <LeaderboardFilter
        rows={STATUS_ROWS}
        onFilter={() => {}}
        onStatusChange={onStatusChange}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: "running" }));
    fireEvent.click(screen.getByTitle(/clear/i));
    expect(screen.getByRole("button", { name: "running" }))
      .toHaveAttribute("aria-pressed", "false");
    expect(onStatusChange).toHaveBeenLastCalledWith("");
  });
});
