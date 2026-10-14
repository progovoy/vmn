/** One ARIA tablist with a roving tab stop (the board's and the job page's). */
import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import Tabs from "../Tabs";

const TABS = ["a", "b", "c"] as const;

function renderTabs(tab: typeof TABS[number], onTab = vi.fn()) {
  render(
    <Tabs
      tabs={TABS} tab={tab} onTab={onTab} label="Pick" className="board-tabs extra"
      panelId="panel" tabId={(t) => `t-${t}`} render={(t) => t.toUpperCase()}
    />,
  );
  return onTab;
}

describe("Tabs", () => {
  it("is a labelled tablist, one tab stop on the selected tab", () => {
    renderTabs("b");
    const list = screen.getByRole("tablist", { name: "Pick" });
    expect(list).toHaveClass("board-tabs", "extra");
    const tabs = screen.getAllByRole("tab");
    expect(tabs.map((t) => t.textContent)).toEqual(["A", "B", "C"]);
    expect(tabs.map((t) => t.tabIndex)).toEqual([-1, 0, -1]);
    expect(tabs[1]).toHaveAttribute("aria-selected", "true");
    expect(tabs[1]).toHaveAttribute("id", "t-b");
    expect(tabs[1]).toHaveAttribute("aria-controls", "panel");
    expect(tabs[1]).toHaveClass("board-tab");
    expect(tabs[1]).toHaveAttribute("type", "button");
  });

  it("opens a clicked tab, and the arrow keys move and open one", () => {
    const onTab = renderTabs("b");
    fireEvent.click(screen.getByText("A"));
    expect(onTab).toHaveBeenLastCalledWith("a");
    fireEvent.keyDown(screen.getByText("B"), { key: "ArrowRight" });
    expect(onTab).toHaveBeenLastCalledWith("c");
    expect(document.activeElement).toBe(screen.getByText("C"));
  });
});
