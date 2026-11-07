/** Plan 32 F4: a column's first sort follows its goal only; a metric
 *  without one sorts ascending, the same as the server and the CLI. */
import { describe, it, expect, vi } from "vitest";
import { boardSortState } from "../boardSortState";

const SCHEMA = { grad_norm: {}, reward_sum: { goal: "max" }, cost: { goal: "min" } };
const firstOrder = (col: string, schema: typeof SCHEMA | null = SCHEMA) => {
  const click = vi.fn();
  boardSortState(null, null, schema, click).onSort(col);
  return click.mock.calls[0][1];
};

describe("boardSortState's first direction", () => {
  it("sorts a metric without a goal ascending, declared or not", () => {
    expect(firstOrder("grad_norm")).toBe("asc");
    expect(firstOrder("throughput_x", null)).toBe("asc");
  });

  it("sorts a max metric high first and a min metric low first", () => {
    expect(firstOrder("reward_sum")).toBe("desc");
    expect(firstOrder("cost")).toBe("asc");
  });

  it("keeps the non-metric columns' own directions", () => {
    expect(firstOrder("tags.owner")).toBe("asc");
    expect(firstOrder("timestamp")).toBe("desc");
    expect(firstOrder("idx")).toBe("desc");
    expect(firstOrder("started_at")).toBe("desc");
    expect(firstOrder("duration_sec")).toBe("desc");
    expect(firstOrder("job:total")).toBe("desc");
    expect(firstOrder("c:total")).toBe("desc");
  });

  it("reads an unflipped goal-less sort as not reversed", () => {
    const s = boardSortState("grad_norm", "asc", SCHEMA, vi.fn());
    expect(s.order).toBe("asc");
    expect(s.reversed).toBe(false);
  });
});
