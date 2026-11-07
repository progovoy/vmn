/** Plan 32 F1: a metric column whose runs override the schema's summary
 *  policy says so — a muted tag on such a cell, `· mixed` in the header, and
 *  "N runs use min" in a group header's title. */
import { describe, it, expect, vi } from "vitest";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Row, { type RowLayout } from "../LeaderboardRow";
import Head, { type SortState } from "../LeaderboardHead";
import { computeColMeta, type ColMeta } from "../leaderboardColumns";
import { aggregateCell } from "../groupHeaderText";
import { row } from "./leaderboardHarness";

const col = (extra: Partial<ColMeta> = {}): ColMeta =>
  ({ goal: null, best: null, isBar: false, min: 0, max: 1, mixed: false, ...extra });

const layout = (meta: ColMeta): RowLayout => ({
  ids: ["m:loss"], styles: [{}], total: 100, metricCols: ["loss"], paramCols: [],
  colMeta: { loss: meta }, showBest: false, runBase: "/ws/test/app/my-app",
});

function cell(metric_policy: Record<string, string> | undefined) {
  render(
    <MemoryRouter><table><tbody>
      <Row row={row(1, { metrics: { loss: 0.2 }, metric_policy } as never)} index={0} isSelected={false}
           isFlash={false} isActive={false} layout={layout(col())} onToggle={() => {}} />
    </tbody></table></MemoryRouter>,
  );
  return document.querySelector('td[data-col-id="m:loss"]') as HTMLElement;
}

describe("a metric cell", () => {
  it("tags a value its run's own policy picked, unlike the schema's", () => {
    const td = cell({ loss: "min" });
    expect(td.querySelector(".policy-tag")?.textContent).toBe("min");
    expect(td.textContent).toContain("0.2");
  });

  it("shows no tag when the run follows the schema", () => {
    expect(cell(undefined).querySelector(".policy-tag")).toBeNull();
  });

  it("tags a run's last over the schema's summary", () => {
    expect(cell({ loss: "last" }).querySelector(".policy-tag")?.textContent).toBe("last");
  });
});

describe("a metric column's meta", () => {
  it("says whether a loaded row overrides the schema's policy", () => {
    const rows = [row(1, { metrics: { loss: 0.2 }, metric_policy: { loss: "min" } } as never),
                  row(2, { metrics: { loss: 0.9 } })];
    expect(computeColMeta(rows, ["loss"], { loss: { goal: "min" } }, null).loss.mixed).toBe(true);
    expect(computeColMeta(rows.slice(1), ["loss"], null, null).loss.mixed).toBe(false);
  });
});

describe("a metric column's header", () => {
  const sort: SortState = { sort: null, order: null, reversed: false, onSort: vi.fn() };
  const head = (meta: ColMeta) => {
    render(<table><Head layout={layout(meta)} sort={sort} edits={{ onResize: vi.fn(), onMove: vi.fn() }} /></table>);
    return document.querySelector('th[data-col-id="m:loss"]') as HTMLElement;
  };

  it("reads `loss · mixed` when a loaded row overrides the schema", () => {
    expect(head(col({ mixed: true })).textContent).toContain("· mixed");
  });

  it("says nothing of policies without an override", () => {
    expect(head(col()).textContent).not.toContain("mixed");
  });
});

describe("a group header's aggregate", () => {
  const agg = { mean: 0.5, best: 0.2, median: 0.4, min: 0.2, max: 0.9, n: 16, goal: "min" as const };

  it("names the runs overriding the schema's policy", () => {
    const mixed = { ...agg, mixed: true, policies: { min: 2 } };
    expect(aggregateCell(mixed, "mean").title).toBe("mean of 16 · 2 runs use min");
  });

  it("says nothing more without an override", () => {
    expect(aggregateCell(agg, "mean").title).toBe("mean of 16");
  });
});
