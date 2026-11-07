/** Plan 32 follow-up: a metric whose runs declare different goals has no
 *  board goal; its header, sort tooltip and the goal hint say `goals differ`
 *  rather than `no goal`, and the hint counts those metrics apart. */
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Head, { type SortState } from "../LeaderboardHead";
import type { RowLayout } from "../LeaderboardRow";
import GoalHint from "../GoalHint";
import { computeColMeta, type ColMeta } from "../leaderboardColumns";
import type { MetricsSchema } from "../../types";

const SCHEMA: MetricsSchema = {
  loss: { goal_conflict: true, goals: { min: 2, max: 1 } },
  acc: { goal: "max" },
};

const col = (extra: Partial<ColMeta> = {}): ColMeta =>
  ({ goal: null, best: null, isBar: false, min: 0, max: 1, ...extra });

function renderHead(meta: Record<string, ColMeta>) {
  const ids = ["m:loss", "m:lr"];
  const layout: RowLayout = {
    ids, styles: ids.map(() => ({})), widths: ids.map(() => 100), total: 200,
    metricCols: ["loss", "lr"], paramCols: [], colMeta: meta, showBest: false, runBase: "/ws/t/app/a",
  };
  const s: SortState = { sort: null, order: null, reversed: false, onSort: vi.fn() };
  render(<table><Head layout={layout} sort={s} check={{ state: "none", onToggle: vi.fn() }} /></table>);
}

const head = (id: string) => document.querySelector(`th[data-col-id="${id}"]`) as HTMLElement;

describe("a metric whose runs declare different goals", () => {
  it("has no goal in its column meta, but a conflict", () => {
    const meta = computeColMeta([], ["loss", "acc"], SCHEMA, null);
    expect(meta.loss).toMatchObject({ goal: null, best: null, goalConflict: true });
    expect(meta.acc.goalConflict).toBeFalsy();
  });

  it("says (goals differ) in its header and sort tooltip, not (no goal)", () => {
    renderHead({ loss: col({ goalConflict: true }), lr: col() });
    expect(head("m:loss").querySelector(".no-goal")).toHaveTextContent("(goals differ)");
    expect(head("m:loss").querySelector(".no-goal")).toHaveAttribute(
      "title", "its runs declare different goals: declare one in conf.yml");
    expect(head("m:loss").querySelector("[title^='sort by']")).toHaveAttribute(
      "title", "sort by loss (goals differ: low first)");
    expect(head("m:lr").querySelector(".no-goal")).toHaveTextContent("(no goal)");
  });

  it("is counted apart in the goal hint", () => {
    render(<MemoryRouter><GoalHint metrics={["loss", "acc", "lr"]} schema={SCHEMA} base="/ws/w/app/a" /></MemoryRouter>);
    const notes = screen.getAllByRole("note");
    expect(notes).toHaveLength(2);
    expect(notes[0]).toHaveTextContent("1 metric has no goal");
    expect(notes[0]).toHaveAttribute("title", "No goal: lr");
    expect(notes[1]).toHaveTextContent("1 metric has conflicting goals — declare one in conf.yml");
    expect(notes[1]).toHaveAttribute("title", "Goals differ: loss (min: 2 runs, max: 1 run)");
  });

  it("alone gives only the conflict line", () => {
    render(<MemoryRouter><GoalHint metrics={["loss"]} schema={SCHEMA} base="/ws/w/app/a" /></MemoryRouter>);
    expect(screen.getByRole("note")).toHaveTextContent("1 metric has conflicting goals");
  });
});
