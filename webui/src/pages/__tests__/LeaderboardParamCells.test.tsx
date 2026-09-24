import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Row, { type RowLayout } from "../LeaderboardRow";
import { row } from "./leaderboardHarness";

const paramCols = ["lr", "dropout", "opt", "amsgrad", "steps"];
const layout: RowLayout = {
  styles: Array.from({ length: 16 }, () => ({})),
  total: 1000, metricCols: [], paramCols, paramBase: 4, tagsIdx: null, noteIdx: 4 + paramCols.length,
  colMeta: {}, showBest: false, runBase: "/ws/test/app/my-app",
};

function renderRow(params: Record<string, unknown>) {
  const noop = () => {};
  render(
    <MemoryRouter>
      <table><tbody>
        <Row
          row={row(1, { params })} index={0} start={0} size={40} isSelected={false} isFlash={false}
          isActive={false} collapsed={null} layout={layout} onToggle={noop} onPrefetch={noop} onFold={noop}
        />
      </tbody></table>
    </MemoryRouter>,
  );
  return Array.from(document.querySelectorAll("td.param-cell"));
}

describe("leaderboard param cells", () => {
  it("formats numeric params without float noise, keeping the full value in the title", () => {
    const [lr, dropout] = renderRow({ lr: 0.0001, dropout: 0.30000000000000004 });
    expect(dropout.textContent).toBe("0.3");
    expect(dropout.getAttribute("title")).toBe("0.30000000000000004");
    expect(lr.textContent).toBe("0.0001");
  });

  it("keeps strings, bools and integers verbatim", () => {
    const cells = renderRow({ opt: "adam", amsgrad: true, steps: 1234567 });
    expect(cells.map((c) => c.textContent)).toEqual(["—", "—", "adam", "true", "1234567"]);
    expect(cells[2].getAttribute("title")).toBe("adam");
  });
});
