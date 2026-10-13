/** Plan 20 C3: sorting from the keyboard and for screen readers, and the
 *  column menu that gives drag/resize their keyboard equivalents. */
import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import Head, { type ColumnEdits, type SortState } from "../LeaderboardHead";
import type { RowLayout } from "../LeaderboardRow";

const IDS = ["check", "idx", "status", "experiment", "m:loss", "m:acc", "p:lr", "when"];

function layout(): RowLayout {
  return {
    ids: IDS, styles: IDS.map(() => ({})), widths: IDS.map(() => 100), total: 800,
    metricCols: ["loss", "acc"], paramCols: ["lr"], colMeta: {}, showBest: false, runBase: "/ws/t/app/a",
  };
}

function renderHead(sort: Partial<SortState> = {}, edits: Partial<ColumnEdits> = {}, onToggle = vi.fn()) {
  const s: SortState = { sort: null, order: null, reversed: false, onSort: vi.fn(), ...sort };
  const e: ColumnEdits = {
    onResize: vi.fn(), onMove: vi.fn(), onShift: vi.fn(), onHide: vi.fn(), onPin: vi.fn(), pinned: [], ...edits,
  };
  render(
    <table><Head layout={layout()} sort={s} edits={e} check={{ state: "none", onToggle }} /></table>,
  );
  return { s, e, onToggle };
}

const head = (id: string) => document.querySelector(`th[data-col-id="${id}"]`) as HTMLElement;
const sortButton = (id: string) => within(head(id)).getByRole("button", { name: /^sort by/i });
const menuButton = (name: string) => screen.getByRole("button", { name: `Column menu: ${name}` });

describe("LeaderboardHead sorting (C3)", () => {
  it("puts a sort button in each sortable header and none in the others", () => {
    renderHead();
    for (const id of ["idx", "m:loss", "m:acc", "when"]) expect(sortButton(id)).toBeInTheDocument();
    for (const id of ["status", "experiment", "p:lr"]) {
      expect(within(head(id)).queryByRole("button", { name: /^sort by/i })).toBeNull();
    }
  });

  it("sorts on Enter and on Space, once per press", () => {
    const { s } = renderHead();
    fireEvent.keyDown(sortButton("m:loss"), { key: "Enter" });
    expect(s.onSort).toHaveBeenCalledWith("loss");
    fireEvent.keyDown(sortButton("when"), { key: " " });
    expect(s.onSort).toHaveBeenLastCalledWith("timestamp");
    expect(s.onSort).toHaveBeenCalledTimes(2);
  });

  it("sorts on a click of the button", () => {
    const { s } = renderHead();
    fireEvent.click(sortButton("idx"));
    expect(s.onSort).toHaveBeenCalledTimes(1);
    expect(s.onSort).toHaveBeenCalledWith("idx");
  });

  it("aria-sort follows the sorted column and its direction", () => {
    renderHead({ sort: "loss", order: "asc" });
    expect(head("m:loss")).toHaveAttribute("aria-sort", "ascending");
    expect(head("m:acc")).toHaveAttribute("aria-sort", "none");
    expect(head("p:lr")).not.toHaveAttribute("aria-sort");
  });

  it("aria-sort reads descending for a descending sort", () => {
    renderHead({ sort: "timestamp", order: "desc" });
    expect(head("when")).toHaveAttribute("aria-sort", "descending");
    expect(head("m:loss")).toHaveAttribute("aria-sort", "none");
  });

  it("keeps the select-all checkbox and the resize grips", () => {
    const { onToggle } = renderHead();
    fireEvent.click(screen.getByRole("checkbox", { name: "Select all visible runs" }));
    expect(onToggle).toHaveBeenCalled();
    expect(within(head("m:loss")).getByRole("separator", { name: "resize column" })).toBeInTheDocument();
  });
});

describe("LeaderboardHead column menu (C3)", () => {
  it("opens a menu without sorting, focusing its first item", () => {
    const { s } = renderHead();
    const trigger = menuButton("loss");
    expect(trigger).toHaveAttribute("aria-haspopup", "menu");
    fireEvent.click(trigger);
    expect(s.onSort).not.toHaveBeenCalled();
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    const menu = screen.getByRole("menu", { name: "loss column" });
    const items = within(menu).getAllByRole("menuitem").map((b) => b.textContent);
    expect(items).toEqual(["Sort", "Hide column", "Pin column", "Move left", "Move right"]);
    expect(document.activeElement).toBe(within(menu).getAllByRole("menuitem")[0]);
  });

  it("moves a column left and right", () => {
    const { e } = renderHead();
    fireEvent.click(menuButton("acc"));
    fireEvent.click(screen.getByRole("menuitem", { name: "Move left" }));
    expect(e.onShift).toHaveBeenCalledWith("m:acc", -1);
    expect(screen.queryByRole("menu")).toBeNull();
    fireEvent.click(menuButton("acc"));
    fireEvent.click(screen.getByRole("menuitem", { name: "Move right" }));
    expect(e.onShift).toHaveBeenLastCalledWith("m:acc", 1);
  });

  it("cannot move a column past the fixed columns", () => {
    renderHead();
    fireEvent.click(menuButton("loss"));
    expect(screen.getByRole("menuitem", { name: "Move left" })).toBeDisabled();
    expect(screen.getByRole("menuitem", { name: "Move right" })).toBeEnabled();
  });

  it("keeps a pinned column among the pinned ones and offers to unpin it", () => {
    renderHead({}, { pinned: ["m:loss"] });
    fireEvent.click(menuButton("loss"));
    expect(screen.getByRole("menuitem", { name: "Unpin column" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Move right" })).toBeDisabled();
  });

  it("sorts, hides and pins from the menu", () => {
    const { s, e } = renderHead({ sort: "loss", order: "desc" });
    fireEvent.click(menuButton("loss"));
    fireEvent.click(screen.getByRole("menuitem", { name: "Reverse sort" }));
    expect(s.onSort).toHaveBeenCalledWith("loss");
    fireEvent.click(menuButton("lr"));
    expect(screen.queryByRole("menuitem", { name: /sort/i })).toBeNull();
    fireEvent.click(screen.getByRole("menuitem", { name: "Hide column" }));
    expect(e.onHide).toHaveBeenCalledWith("p:lr");
    fireEvent.click(menuButton("lr"));
    fireEvent.click(screen.getByRole("menuitem", { name: "Pin column" }));
    expect(e.onPin).toHaveBeenCalledWith("p:lr");
  });

  it("closes on Escape and gives focus back to its button", () => {
    renderHead();
    fireEvent.click(menuButton("loss"));
    fireEvent.keyDown(document.activeElement!, { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
    expect(document.activeElement).toBe(menuButton("loss"));
  });

  it("offers no menu on the fixed columns without actions", () => {
    renderHead();
    for (const name of ["status", "experiment"]) {
      expect(screen.queryByRole("button", { name: `Column menu: ${name}` })).toBeNull();
    }
  });
});
