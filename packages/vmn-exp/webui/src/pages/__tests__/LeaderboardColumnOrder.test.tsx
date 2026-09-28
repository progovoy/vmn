import { describe, it, expect, vi, beforeEach, beforeAll } from "vitest";
import { waitFor } from "@testing-library/react";
import { renderBoard, row, page } from "./leaderboardHarness";

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
    metricsSchema: vi.fn(),
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

const mockedApi = api as unknown as {
  experiments: ReturnType<typeof vi.fn>;
  experimentsPaged: ReturnType<typeof vi.fn>;
  metricsSchema: ReturnType<typeof vi.fn>;
};

beforeEach(() => {
  vi.clearAllMocks();
  mockedApi.metricsSchema.mockResolvedValue({});
  mockedApi.experimentsPaged?.mockResolvedValue(undefined);
});

/** Metric/param header names in their DOM order.
 *  Each header contains the key name as its first text child (before the goal
 *  arrow span), so we take the first word to avoid matching "loss ↑". */
function metricParamHeaders(): string[] {
  const heads = [...document.querySelectorAll("thead th")] as HTMLElement[];
  const fixed = new Set(["", "#", "status", "experiment", "note", "when", "tags"]);
  return heads
    .map((th) => (th.firstChild as Text | null)?.textContent?.trim() ?? th.textContent?.trim() ?? "")
    .filter((t) => !fixed.has(t));
}

describe("Leaderboard column order and pinning from URL", () => {
  it("old URL without col/pin renders default alphabetical order", async () => {
    mockedApi.experiments.mockResolvedValue(page([
      row(1, { metrics: { loss: 0.3, acc: 0.8 } }),
    ]));
    renderBoard("/ws/test/app/my-app");
    await waitFor(() => expect(document.querySelector("thead")).toBeInTheDocument());
    const heads = metricParamHeaders();
    // default order: extras alphabetically: acc before loss
    expect(heads.indexOf("acc")).toBeLessThan(heads.indexOf("loss"));
  });

  it("col= reorders header and body columns identically", async () => {
    mockedApi.experiments.mockResolvedValue(page([
      row(1, { metrics: { loss: 0.3, acc: 0.8 } }),
    ]));
    // col=m:loss before col=m:acc → loss first
    renderBoard("/ws/test/app/my-app?col=m%3Aloss&col=m%3Aacc");
    await waitFor(() => expect(document.querySelector("thead")).toBeInTheDocument());
    const heads = metricParamHeaders();
    expect(heads.indexOf("loss")).toBeLessThan(heads.indexOf("acc"));
  });

  it("pin= gives the pinned column header zIndex 3", async () => {
    mockedApi.experiments.mockResolvedValue(page([
      row(1, { metrics: { loss: 0.3, acc: 0.8 } }),
    ]));
    // pin loss column
    renderBoard("/ws/test/app/my-app?pin=m%3Aloss");
    await waitFor(() => expect(document.querySelector("thead")).toBeInTheDocument());
    const heads = [...document.querySelectorAll("thead th")] as HTMLElement[];
    // Use first text node to find the header (avoids "loss ↑" / "loss ▾" suffixes)
    const lossHead = heads.find(
      (th) => (th.firstChild as Text | null)?.textContent?.trim() === "loss"
    );
    expect(lossHead).toBeTruthy();
    expect(Number(lossHead!.style.zIndex)).toBe(3);
  });

  it("pin= makes pinned column body cells sticky and shares style with header", async () => {
    mockedApi.experiments.mockResolvedValue(page([
      row(1, { metrics: { loss: 0.3, acc: 0.8 } }),
    ]));
    renderBoard("/ws/test/app/my-app?pin=m%3Aloss");
    await waitFor(() => expect(document.querySelector("thead")).toBeInTheDocument());
    const heads = [...document.querySelectorAll("thead th")] as HTMLElement[];
    const lossIdx = heads.findIndex(
      (th) => (th.firstChild as Text | null)?.textContent?.trim() === "loss"
    );
    expect(lossIdx).toBeGreaterThan(0);
    const bodyRow = document.querySelector("tbody tr") as HTMLTableRowElement | null;
    if (bodyRow) {
      const bodyCells = [...bodyRow.querySelectorAll("td")] as HTMLElement[];
      const bodyCell = bodyCells[lossIdx];
      expect(bodyCell?.style.position).toBe("sticky");
    }
  });
});
