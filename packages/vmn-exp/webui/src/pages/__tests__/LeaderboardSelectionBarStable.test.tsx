import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import LeaderboardSelectionBar from "../LeaderboardSelectionBar";
import { MAX_COMPARE_RUNS } from "../compareRunsData";
import barCss from "../selectionBar.css?raw";

const runs = (n: number) => Array.from({ length: n }, (_, i) => `0.0.${i + 1}-dev.x`);

function Where() {
  const loc = useLocation();
  return <output data-testid="where">{loc.pathname + loc.search}</output>;
}

function renderBar(n: number, over: Partial<Parameters<typeof LeaderboardSelectionBar>[0]> = {}) {
  const props = {
    selected: runs(n), total: 900, base: "/ws/t/app/a", showUnarchive: false,
    archiving: false, archiveError: null, onClear: vi.fn(), onSelectAll: vi.fn(), onArchive: vi.fn(),
    ...over,
  };
  const ui = (p: typeof props) => (
    <MemoryRouter initialEntries={["/ws/t/app/a"]}>
      <Routes><Route path="*" element={<><LeaderboardSelectionBar {...p} /><Where /></>} /></Routes>
    </MemoryRouter>
  );
  const r = render(ui(props));
  return { ...r, props, rerenderWith: (m: number, o: Partial<typeof props> = {}) =>
    r.rerender(ui({ ...props, ...o, selected: runs(m) })) };
}

const region = () => screen.getByRole("region", { name: "Selection" });
const actionNames = () =>
  Array.from(region().querySelectorAll(".sel-actions button")).map((b) => b.textContent!.trim());
const action = (name: RegExp) => within(region()).getByRole("button", { name });
const reason = (el: HTMLElement) =>
  el.getAttribute("aria-describedby")!.split(" ").map((id) => document.getElementById(id)?.textContent).join(" ");

describe("a selection bar that keeps its shape as the count changes", () => {
  // Plan 20 M3 replaced Code diff / Compare in table / Overlay curves with
  // one Compare (N); only its count changes, in a fixed-width slot.
  const withoutCount = (names: string[]) => names.map((n) => n.replace(/ \(\d+\)$/, ""));

  it("renders the same actions, in the same order, at 1, 2 and 3 runs", () => {
    const { rerenderWith } = renderBar(1);
    const at1 = withoutCount(actionNames());
    rerenderWith(2);
    const at2 = withoutCount(actionNames());
    rerenderWith(3);
    expect(at1).toEqual(["Compare", "Archive"]);
    expect(at2).toEqual(at1);
    expect(withoutCount(actionNames())).toEqual(at1);
  });

  it("keeps counts out of every action label but Compare's", () => {
    renderBar(3);
    expect(actionNames()[0]).toBe("Compare (3)");
    for (const name of actionNames().slice(1)) expect(name).not.toMatch(/\d/);
  });

  it("marks what one run can't do aria-disabled, saying why", () => {
    renderBar(1);
    const compare = action(/^compare/i);
    expect(compare).toHaveAttribute("aria-disabled", "true");
    expect(compare).toHaveAttribute("title", "Select 2 or more runs");
    expect(reason(compare)).toBe("Select 2 or more runs");
    expect(action(/^archive$/i)).toBeEnabled();
  });

  it("enables Compare from two runs on", () => {
    const { rerenderWith } = renderBar(2);
    expect(action(/^compare/i)).toBeEnabled();
    expect(action(/^compare/i)).not.toHaveAttribute("aria-describedby");
    rerenderWith(3);
    expect(action(/^compare/i)).not.toHaveAttribute("aria-disabled");
  });

  it("keeps Compare enabled past the table's cap (each tab caps itself)", () => {
    renderBar(MAX_COMPARE_RUNS + 1);
    expect(action(/^compare/i)).not.toHaveAttribute("aria-disabled");
  });

  it("goes nowhere from a disabled action, and to the Compare page from an enabled one", () => {
    const { rerenderWith } = renderBar(1);
    fireEvent.click(action(/^compare/i));
    expect(screen.getByTestId("where").textContent).toBe("/ws/t/app/a");
    rerenderWith(2);
    fireEvent.click(action(/^compare/i));
    expect(screen.getByTestId("where").textContent)
      .toBe(`/ws/t/app/a/compare-runs?tab=curves&sel=${encodeURIComponent("0.0.1-dev.x")}&sel=${encodeURIComponent("0.0.2-dev.x")}`);
  });

  it("keeps the select-all slot in place once every match is selected, hidden from the reader", () => {
    const { rerenderWith } = renderBar(1, { total: 3 });
    expect(within(region()).getByRole("button", { name: /select all 3 matching/i })).toBeInTheDocument();
    rerenderWith(3, { total: 3 });
    expect(within(region()).queryByRole("button", { name: /select all/i })).toBeNull();
    const slot = region().querySelector(".sel-all") as HTMLElement;
    expect(slot).not.toBeNull();
    expect(slot.style.visibility).toBe("hidden");
  });

  it("hands focus to the first available action when select-all hides itself", () => {
    const { rerenderWith } = renderBar(1, { total: 3 });
    within(region()).getByRole("button", { name: /select all 3 matching/i }).focus();
    rerenderWith(3, { total: 3 });
    expect(document.activeElement).toBe(action(/^compare/i));
  });

  it("puts select-all in the label area, not among the actions", () => {
    renderBar(1);
    const all = within(region()).getByRole("button", { name: /select all 500 matching/i });
    expect(all.closest(".sel-label")).not.toBeNull();
    expect(all.closest(".sel-actions")).toBeNull();
  });

  it("reserves the plural label's width, so 'run' and 'runs' fill the same box", () => {
    renderBar(1);
    const label = region().querySelector(".sel-label-text") as HTMLElement;
    expect(label.textContent).toBe("run selected");
    expect(label).toHaveAttribute("data-widest", "runs selected");
  });

  it("reports an archive failure in an alert outside the bar", () => {
    renderBar(1, { archiveError: "exp_archive failed" });
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("exp_archive failed");
    expect(region().contains(alert)).toBe(false);
  });
});

describe("the selection bar's stylesheet", () => {
  const rule = (sel: string) => {
    const m = barCss.match(new RegExp(`(^|\\n)${sel.replace(/[.]/g, "\\.")}\\s*\\{([^}]*)\\}`));
    return m ? m[2] : "";
  };

  it("reserves four tabular digits in the badge", () => {
    const badge = rule(".sel-badge");
    expect(badge).toMatch(/font-variant-numeric:\s*tabular-nums/);
    expect(badge).toMatch(/min-width:\s*[4-9](\.\d+)?ch/);
  });

  it("stacks the widest label under the shown one", () => {
    expect(barCss).toMatch(/\.sel-label-text::after\s*\{[^}]*content:\s*attr\(data-widest\)/);
  });

  it("animates no width, height or position on a count change", () => {
    expect(barCss).not.toMatch(/transition[^;]*(width|height|left|right|all)/);
  });
});
