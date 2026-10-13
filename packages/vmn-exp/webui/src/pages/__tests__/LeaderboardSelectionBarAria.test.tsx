import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import LeaderboardSelectionBar from "../LeaderboardSelectionBar";

const runs = (n: number) => Array.from({ length: n }, (_, i) => `0.0.${i + 1}-dev.x`);

function Where() {
  const loc = useLocation();
  return <output data-testid="where">{loc.pathname + loc.search}</output>;
}

function renderBar(n: number) {
  render(
    <MemoryRouter initialEntries={["/ws/t/app/a"]}>
      <Routes><Route path="*" element={<>
        <LeaderboardSelectionBar
          selected={runs(n)} total={900} base="/ws/t/app/a" showUnarchive={false}
          archiving={false} archiveError={null} onClear={vi.fn()} onSelectAll={vi.fn()} onArchive={vi.fn()}
        />
        <Where />
      </>} /></Routes>
    </MemoryRouter>,
  );
}

const region = () => screen.getByRole("region", { name: "Selection" });
const action = (name: RegExp) => within(region()).getByRole("button", { name });
const where = () => screen.getByTestId("where").textContent;

describe("the selection bar's inapplicable actions", () => {
  // Plan 20 M3: Compare (N) is the bar's one count-gated action.
  it("are marked aria-disabled, not natively disabled, so they stay in the Tab order", () => {
    renderBar(1);
    const compare = action(/^compare/i);
    expect(compare).toHaveAttribute("aria-disabled", "true");
    expect(compare).not.toHaveAttribute("disabled");
    expect(compare).toHaveAttribute("title", "Select 2 or more runs");
    expect(compare).toHaveAccessibleDescription("Select 2 or more runs");
  });

  it("take keyboard focus, announcing why they can't run", () => {
    renderBar(1);
    const compare = action(/^compare/i);
    expect(compare.tabIndex).toBe(0);
    compare.focus();
    expect(document.activeElement).toBe(compare);
    expect(compare).toHaveAccessibleDescription("Select 2 or more runs");
  });

  it("do nothing when activated", () => {
    renderBar(1);
    fireEvent.click(action(/^compare/i));
    expect(where()).toBe("/ws/t/app/a");
  });

  it("drop the marker once they apply", () => {
    renderBar(2);
    const compare = action(/^compare/i);
    expect(compare).not.toHaveAttribute("aria-disabled");
    expect(compare).not.toHaveAccessibleDescription();
  });
});

describe("the selection bar stylesheet", () => {
  it("styles aria-disabled actions like disabled buttons", async () => {
    const css = (await import("../selectionBar.css?raw")).default;
    expect(css).toMatch(/\[aria-disabled="true"\][^{]*\{[^}]*opacity:\s*0\.5/);
  });
});
