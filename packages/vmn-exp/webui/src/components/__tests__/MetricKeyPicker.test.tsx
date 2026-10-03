import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

// A window of the first `shown` rows, as a scrolled-to-top list would render.
const view = { shown: 20 };
vi.mock("@tanstack/react-virtual", () => ({
  useVirtualizer: ({ count }: { count: number }) => ({
    getTotalSize: () => count * 24,
    getVirtualItems: () =>
      Array.from({ length: Math.min(count, view.shown) }, (_, index) => ({
        index, key: index, start: index * 24, size: 24, end: (index + 1) * 24,
      })),
  }),
}));

import MetricKeyPicker, { KEYS_PAGE } from "../MetricKeyPicker";

const NAMES = Array.from({ length: 2500 }, (_, i) => `train/m${String(i).padStart(4, "0")}`);

function server() {
  return vi.fn(async ({ prefix, offset, limit }: { prefix: string; offset: number; limit: number }) => {
    const names = NAMES.filter((n) => n.startsWith(prefix));
    return {
      keys: names.slice(offset, offset + limit).map((name) => ({ name, count: 10 })),
      total: names.length, offset, limit,
    };
  });
}

beforeEach(() => { view.shown = 20; });

describe("MetricKeyPicker", () => {
  it("loads one page and renders only the visible rows", async () => {
    const fetchPage = server();
    render(<MetricKeyPicker fetchPage={fetchPage} selected={[]} onToggle={() => {}} />);
    await screen.findByText("train/m0000");
    expect(fetchPage).toHaveBeenCalledTimes(1);
    expect(fetchPage).toHaveBeenCalledWith({ prefix: "", offset: 0, limit: KEYS_PAGE });
    expect(screen.getAllByRole("checkbox")).toHaveLength(20);
    expect(screen.getByText(/2500 metrics/)).toBeTruthy();
  });

  it("loads the next page once the list is scrolled to the loaded end", async () => {
    view.shown = KEYS_PAGE;
    const fetchPage = server();
    render(<MetricKeyPicker fetchPage={fetchPage} selected={[]} onToggle={() => {}} />);
    await waitFor(() =>
      expect(fetchPage).toHaveBeenCalledWith({ prefix: "", offset: KEYS_PAGE, limit: KEYS_PAGE }));
  });

  it("searches by prefix on the server", async () => {
    const fetchPage = server();
    render(<MetricKeyPicker fetchPage={fetchPage} selected={[]} onToggle={() => {}} />);
    await screen.findByText("train/m0000");
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "train/m2499" } });
    await screen.findByText("train/m2499");
    expect(fetchPage).toHaveBeenLastCalledWith({ prefix: "train/m2499", offset: 0, limit: KEYS_PAGE });
    expect(screen.getAllByRole("checkbox")).toHaveLength(1);
  });

  it("toggles keys and shows the selected ones checked", async () => {
    const onToggle = vi.fn();
    render(<MetricKeyPicker fetchPage={server()} selected={["train/m0001"]} onToggle={onToggle} />);
    const box = await screen.findByRole("checkbox", { name: "train/m0001" });
    expect((box as HTMLInputElement).checked).toBe(true);
    fireEvent.click(screen.getByRole("checkbox", { name: "train/m0002" }));
    expect(onToggle).toHaveBeenCalledWith("train/m0002");
  });
});
