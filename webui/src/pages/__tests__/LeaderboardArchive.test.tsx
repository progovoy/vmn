import { describe, it, expect, vi, beforeEach, beforeAll } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";

beforeAll(() => {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
});

vi.mock("../../api", () => ({
  api: {
    experiments: vi.fn(),
    experimentsPaged: vi.fn(),
    experimentsColumns: vi.fn(),
    metricsSchema: vi.fn(),
    facets: vi.fn(),
    experiment: vi.fn(),
    action: vi.fn(),
    job: vi.fn(),
  },
  appName: (tag: string) => tag.replaceAll("-", "/"),
}));
vi.mock("../../components/ParamPlots", () => ({ default: () => null }));
vi.mock("../../components/NewExperiment", () => ({ default: () => null }));
vi.mock("@tanstack/react-virtual", () => ({
  useVirtualizer: ({ count }: { count: number }) => ({
    getTotalSize: () => count * 48,
    getVirtualItems: () =>
      Array.from({ length: count }, (_, index) => ({
        index, key: index, start: index * 48, size: 48, end: (index + 1) * 48,
      })),
  }),
}));

import { api } from "../../api";
import { page, renderBoard, row, urlParams } from "./leaderboardHarness";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const v = (i: number) => `0.0.${i}-dev.x`;
const job = (status: string) => ({ id: "j1", status, command: [], exit_code: status === "running" ? null : 0, log: "", noop: false });

beforeEach(() => {
  vi.clearAllMocks();
  m.metricsSchema.mockResolvedValue({});
  m.facets.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.experimentsColumns.mockRejectedValue(Object.assign(new Error("nf"), { status: 404 }));
  m.experiments.mockResolvedValue(page([row(1), row(2, { archived: true })]));
  m.experimentsPaged.mockResolvedValue({ rows: [row(1), row(2, { archived: true })], total: 2 });
  m.action.mockResolvedValue(job("running"));
  m.job.mockResolvedValue(job("succeeded"));
});

describe("archived filter", () => {
  it("asks for archived rows once the toggle is on, and keeps it in the URL", async () => {
    renderBoard();
    const toggle = await screen.findByRole("button", { name: "archived" });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(toggle);
    await waitFor(() => expect(urlParams().get("archived")).toBe("1"));
    await waitFor(() =>
      expect(m.experimentsPaged).toHaveBeenCalledWith(
        "test", "my-app", expect.objectContaining({ archived: true, offset: 0 }),
      ),
    );
    expect(screen.getByRole("button", { name: "archived" })).toHaveAttribute("aria-pressed", "true");
  });

  it("mutes archived rows", async () => {
    renderBoard("/ws/test/app/my-app?archived=1");
    const link = await screen.findByRole("link", { name: v(2) });
    expect(link.closest("tr")).toHaveClass("archived");
    expect(screen.getByRole("link", { name: v(1) }).closest("tr")).not.toHaveClass("archived");
  });
});

describe("bulk archive", () => {
  it("archives the selection after confirming, then clears it", async () => {
    renderBoard(`/ws/test/app/my-app?sel=${v(1)}`);
    fireEvent.click(await screen.findByRole("button", { name: "Archive" }));
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent("Archive 1 run?");
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(m.action).toHaveBeenCalledWith("test", "my-app", "exp_archive", { verstrs: [v(1)] });
    await waitFor(() => expect(urlParams().getAll("sel")).toEqual([]));
  });

  it("unarchives through exp_unarchive", async () => {
    renderBoard(`/ws/test/app/my-app?archived=1&sel=${v(2)}`);
    fireEvent.click(await screen.findByRole("button", { name: "Unarchive" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(m.action).toHaveBeenCalledWith("test", "my-app", "exp_unarchive", { verstrs: [v(2)] });
  });

  it("does nothing when the dialog is cancelled or escaped", async () => {
    renderBoard(`/ws/test/app/my-app?sel=${v(1)}`);
    fireEvent.click(await screen.findByRole("button", { name: "Archive" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Archive" }));
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(m.action).not.toHaveBeenCalled();
    expect(urlParams().getAll("sel")).toEqual([v(1)]);
  });
});
