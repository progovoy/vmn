/** A metric whose steps went back without a rewind (a restarted step
 *  counter) is marked beyond the run page: on its board cell, from the row's
 *  `step_restarts`, and on its Compare table cell, from the run's detail. */
import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Row, { type RowLayout } from "../LeaderboardRow";
import CompareRunsTable from "../CompareRunsTable";
import type { ColMeta } from "../leaderboardColumns";
import type { ExperimentDetail } from "../../types";
import { restartText } from "../../util/stepRestart";
import { row } from "./leaderboardHarness";

const META: ColMeta = { goal: null, best: null, isBar: false, min: 0, max: 1, mixed: false };
const LAYOUT: RowLayout = {
  ids: ["m:best"], styles: [{}], total: 100, metricCols: ["best"], paramCols: [],
  colMeta: { best: META }, showBest: false, runBase: "/ws/test/app/my-app",
};
const WENT_BACK = { best: { from: 120, to: 0 } };

function boardCell(step_restarts?: Record<string, { from: number; to: number }>) {
  render(
    <MemoryRouter><table><tbody>
      <Row row={row(1, { metrics: { best: 0.989 }, step_restarts } as never)} index={0}
           isSelected={false} isFlash={false} isActive={false} layout={LAYOUT} onToggle={() => {}} />
    </tbody></table></MemoryRouter>,
  );
  return document.querySelector('td[data-col-id="m:best"]') as HTMLElement;
}

describe("restartText", () => {
  it("names the write when the run page knows it, else just the steps", () => {
    expect(restartText({ from: 120, to: 0, write: 122 })).toBe("steps went back from 120 to 0 at write 122");
    expect(restartText({ from: 120, to: 0 })).toBe("steps went back from 120 to 0");
  });
});

describe("a board cell", () => {
  it("marks a metric whose steps went back, keeping its last write", () => {
    const td = boardCell(WENT_BACK);
    expect(td.textContent).toContain("0.989");
    const mark = td.querySelector(".restart-tag");
    expect(mark).not.toBeNull();
    expect(mark).toHaveAttribute("title", "steps went back from 120 to 0 · the value is the last write");
  });

  it("marks nothing when the steps only rose", () => {
    expect(boardCell(undefined).querySelector(".restart-tag")).toBeNull();
  });
});

describe("the Compare table", () => {
  const detail = (restarts?: ExperimentDetail["step_restarts"]) =>
    ({ metrics: { best: 0.989 }, metadata: {}, params: {}, step_restarts: restarts }) as unknown as ExperimentDetail;

  it("marks the run's cell of a metric whose steps went back", () => {
    render(
      <MemoryRouter>
        <CompareRunsTable verstrs={["a", "b"]} base="/ws/w/app/app" schema={null} onlyDiffering={false}
          details={[detail({ best: { from: 120, to: 0, write: 122 } }), detail()]} />
      </MemoryRouter>,
    );
    const marks = document.querySelectorAll('tr[data-section="metrics"] .restart-tag');
    expect(marks).toHaveLength(1);
    expect(marks[0].getAttribute("title")).toContain(restartText({ from: 120, to: 0, write: 122 }));
  });
});
