/** Plan 20 M3: the selection bar's one primary Compare (N) plus
 *  Archive/Unarchive; Compare opens the Compare page's curves tab. */
import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import LeaderboardSelectionBar from "../LeaderboardSelectionBar";
import barCss from "../selectionBar.css?raw";

const runs = (n: number) => Array.from({ length: n }, (_, i) => `0.0.${i + 1}-dev.x`);

function Where() {
  const loc = useLocation();
  return <output data-testid="where">{loc.pathname + loc.search}</output>;
}

function renderBar(n: number, showUnarchive = false) {
  render(
    <MemoryRouter initialEntries={["/ws/t/app/a"]}>
      <Routes><Route path="*" element={<>
        <LeaderboardSelectionBar
          selected={runs(n)} total={900} base="/ws/t/app/a" showUnarchive={showUnarchive}
          archiving={false} archiveError={null} onClear={vi.fn()} onSelectAll={vi.fn()} onArchive={vi.fn()}
        />
        <Where />
      </>} /></Routes>
    </MemoryRouter>,
  );
}

const region = () => screen.getByRole("region", { name: "Selection" });
const actions = () => Array.from(region().querySelectorAll(".sel-actions button"))
  .map((b) => b.textContent!.trim());
const compare = () => within(region()).getByRole("button", { name: /^compare/i });

describe("the selection bar's Compare", () => {
  it("is the one primary action, beside Archive and Unarchive", () => {
    renderBar(3, true);
    expect(actions()).toEqual(["Compare (3)", "Archive", "Unarchive"]);
    expect(compare()).toHaveClass("primary");
    expect(region().querySelectorAll(".sel-actions .primary")).toHaveLength(1);
  });

  it("is disabled below two runs, saying why", () => {
    renderBar(1);
    expect(compare()).toHaveAttribute("aria-disabled", "true");
    expect(compare()).toHaveAccessibleDescription("Select 2 or more runs");
    fireEvent.click(compare());
    expect(screen.getByTestId("where").textContent).toBe("/ws/t/app/a");
  });

  it("opens the curves tab of the Compare page with the selection", () => {
    renderBar(3);
    fireEvent.click(compare());
    expect(screen.getByTestId("where").textContent).toBe(
      "/ws/t/app/a/compare-runs?tab=curves&sel=0.0.1-dev.x&sel=0.0.2-dev.x&sel=0.0.3-dev.x",
    );
  });

  it("keeps the count in a fixed-width tabular slot, so the bar keeps its size", () => {
    renderBar(3);
    const count = compare().querySelector(".sel-count")!;
    expect(count.textContent).toBe("(3)");
    const rule = barCss.match(/(^|\n)\.sel-count\s*\{([^}]*)\}/)?.[2] ?? "";
    expect(rule).toMatch(/font-variant-numeric:\s*tabular-nums/);
    expect(rule).toMatch(/min-width:\s*\d+(\.\d+)?ch/);
  });
});
