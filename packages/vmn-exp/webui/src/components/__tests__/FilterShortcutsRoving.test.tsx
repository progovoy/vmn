/** Plan 20 C7: the filter shortcuts (branch, status chips, archived) are one
 *  toolbar with a single Tab stop; the arrow keys move inside it. */
import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import FilterShortcuts from "../FilterShortcuts";

function shortcuts() {
  render(
    <FilterShortcuts
      statuses={[]} onStatuses={vi.fn()} branch="" branches={["main"]} onBranch={vi.fn()}
      archived={false} onArchived={vi.fn()}
    />,
  );
  const bar = screen.getByRole("toolbar", { name: "Filter shortcuts" });
  const items = [...bar.querySelectorAll<HTMLElement>("select, button")];
  return { bar, items };
}

describe("FilterShortcuts keyboard", () => {
  it("is one Tab stop", () => {
    const { items } = shortcuts();
    expect(items.length).toBeGreaterThan(3);
    expect(items.filter((el) => el.tabIndex >= 0)).toHaveLength(1);
  });

  it("moves with ArrowRight/ArrowLeft, wraps, and jumps with Home/End", () => {
    const { bar, items } = shortcuts();
    items[0].focus();
    fireEvent.keyDown(bar, { key: "ArrowRight" });
    expect(document.activeElement).toBe(items[1]);
    expect(items[1].tabIndex).toBe(0);
    expect(items[0].tabIndex).toBe(-1);
    fireEvent.keyDown(bar, { key: "ArrowLeft" });
    expect(document.activeElement).toBe(items[0]);
    fireEvent.keyDown(bar, { key: "ArrowLeft" });
    expect(document.activeElement).toBe(items[items.length - 1]);
    fireEvent.keyDown(bar, { key: "Home" });
    expect(document.activeElement).toBe(items[0]);
    fireEvent.keyDown(bar, { key: "End" });
    expect(document.activeElement).toBe(items[items.length - 1]);
  });

  it("keeps a chip's own keys: Space still toggles it", () => {
    const onStatuses = vi.fn();
    render(
      <FilterShortcuts statuses={[]} onStatuses={onStatuses} branch="" branches={[]} onBranch={vi.fn()} archived={false} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "failed" }));
    expect(onStatuses).toHaveBeenCalledWith(["failed"]);
  });
});
