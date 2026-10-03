import { describe, it, expect, vi } from "vitest";
import { fireEvent, screen } from "@testing-library/react";

vi.mock("@tanstack/react-virtual", () => ({
  useVirtualizer: ({ count }: { count: number }) => ({
    getTotalSize: () => count * 24,
    getVirtualItems: () =>
      Array.from({ length: Math.min(count, 30) }, (_, index) => ({
        index, key: index, start: index * 24, size: 24, end: (index + 1) * 24,
      })),
  }),
}));

import TrainingCurves, { MANY_KEYS, SHOWN_BY_DEFAULT } from "../TrainingCurves";
import { renderWithClient } from "../../test-utils";
import type { SeriesPoint } from "../../types";

const two: SeriesPoint[] = [{ step: 0, value: 1, ts: null }, { step: 1, value: 2, ts: null }];
const names = Array.from({ length: MANY_KEYS + 50 }, (_, i) => `m${String(i).padStart(3, "0")}`);
const SERIES = Object.fromEntries(names.map((n) => [n, two]));

const fetchKeys = vi.fn(async ({ prefix, offset, limit }: { prefix: string; offset: number; limit: number }) => {
  const found = names.filter((n) => n.startsWith(prefix));
  return {
    keys: found.slice(offset, offset + limit).map((name) => ({ name, count: 2 })),
    total: found.length, offset, limit,
  };
});

const charted = () => screen.queryAllByTestId("metric-chart").map((el) => el.getAttribute("data-metric"));

describe("TrainingCurves with many metrics", () => {
  it("charts a few metrics and offers the rest through the key picker", async () => {
    renderWithClient(<TrainingCurves series={SERIES} fetchKeys={fetchKeys} />);
    expect(charted()).toEqual(names.slice(0, SHOWN_BY_DEFAULT));
    fireEvent.click(await screen.findByRole("checkbox", { name: "m020" }));
    expect(charted()).toContain("m020");
    fireEvent.click(screen.getByRole("checkbox", { name: "m000" }));
    expect(charted()).not.toContain("m000");
  });

  it("charts every metric when there are few", () => {
    const few = Object.fromEntries(names.slice(0, 5).map((n) => [n, two]));
    renderWithClient(<TrainingCurves series={few} fetchKeys={fetchKeys} />);
    expect(charted()).toEqual(names.slice(0, 5));
    expect(screen.queryByRole("searchbox", { name: "metric keys" })).toBeNull();
  });
});
