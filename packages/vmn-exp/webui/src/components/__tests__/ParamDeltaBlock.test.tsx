/** K1/D2: the params an experiments-diff flags (`param: true`) get their own
 *  "params changed" block — a count and one row per param — apart from metrics. */
import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import type { DiffDelta } from "../../types";
import ParamDeltaBlock from "../ParamDeltaBlock";
import css from "../ParamDeltaBlock.css?raw";

const d = (from: number | null, to: number | null, param: boolean): DiffDelta =>
  ({ from, to, goal: null, param });

describe("ParamDeltaBlock", () => {
  it("counts the changed params and lists each with both sides, metrics left out", () => {
    render(<ParamDeltaBlock deltas={{
      loss: d(1, 0.5, false), lr: d(0.1, 0.01, true), batch_size: d(32, null, true),
    }} />);
    const block = screen.getByRole("region", { name: "Params changed" });
    expect(within(block).getByRole("heading")).toHaveTextContent(/params changed\s*2/i);
    const rows = within(block).getAllByRole("row").slice(1)
      .map((r) => within(r).getAllByRole("cell").map((c) => c.textContent)
        .reduce((acc, t) => `${acc} ${t}`, within(r).getByRole("rowheader").textContent ?? ""));
    expect(rows).toEqual(["batch_size 32 –", "lr 0.1 0.01"]);
    expect(within(block).queryByText("loss")).toBeNull();
  });

  it("takes the side headers it is given", () => {
    render(<ParamDeltaBlock deltas={{ lr: d(0.1, 0.01, true) }}
      heads={[<th key="a">@1 base</th>, <th key="b">@2</th>]} />);
    expect(screen.getByRole("columnheader", { name: "@1 base" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "@2" })).toBeInTheDocument();
  });

  it("renders nothing without a changed param", () => {
    const { container } = render(<ParamDeltaBlock deltas={{ loss: d(1, 0.5, false), lr: d(1, 1, true) }} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("keeps param names as typed (D3)", () => {
    const rule = /\.param-deltas th\[scope="row"\]\s*\{([^}]*)\}/.exec(css)?.[1] ?? "";
    expect(rule).toMatch(/text-transform:\s*none/);
  });
});
