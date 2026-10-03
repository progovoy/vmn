import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, fireEvent } from "@testing-library/react";
import { renderWithClient } from "../../test-utils";

vi.mock("../../apiCache", async (orig) => ({
  ...(await orig<typeof import("../../apiCache")>()),
  apiCache: { status: vi.fn(), resync: vi.fn() },
}));

import { apiCache } from "../../apiCache";
import CacheResync, { progressLine } from "../CacheResync";

const m = apiCache as unknown as Record<string, ReturnType<typeof vi.fn>>;
const idle = { workspace: "w", state: "idle", progress: { done: 0, total: 0 }, drift: 2,
  rebuilds: 0, last_rebuild_reason: null, journal_lag_sec: 1.5, apps: {} };

beforeEach(() => vi.clearAllMocks());

describe("CacheResync", () => {
  it("formats the rebuild progress line", () => {
    expect(progressLine({ done: 41000, total: 100000 })).toBe("rebuilding: 41,000 / 100,000 records");
  });

  it("resyncs and rebuilds the workspace", async () => {
    m.status.mockResolvedValue(idle);
    m.resync.mockResolvedValue({ ...idle, state: "rebuilding", progress: { done: 5, total: 10 } });
    renderWithClient(<CacheResync ws="w" />);
    fireEvent.click(await screen.findByRole("button", { name: "Resync" }));
    expect(m.resync).toHaveBeenCalledWith("w", false);
    fireEvent.click(screen.getByRole("button", { name: "Rebuild" }));
    expect(m.resync).toHaveBeenCalledWith("w", true);
    expect(await screen.findByText("rebuilding: 5 / 10 records")).toBeTruthy();
  });

  it("shows the drift count", async () => {
    m.status.mockResolvedValue(idle);
    renderWithClient(<CacheResync ws="w" />);
    expect(await screen.findByText(/drift 2/)).toBeTruthy();
  });

  it("renders nothing for a non-admin", async () => {
    m.status.mockRejectedValue(Object.assign(new Error("Forbidden"), { status: 403 }));
    const { container } = renderWithClient(<CacheResync ws="w" />);
    await vi.waitFor(() => expect(m.status).toHaveBeenCalled());
    expect(container.textContent).toBe("");
  });
});
