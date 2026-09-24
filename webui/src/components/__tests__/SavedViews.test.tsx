import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import SavedViews from "../SavedViews";
import { listViews, saveView } from "../../util/savedViews";

beforeEach(() => localStorage.clear());

const trigger = () => screen.getByRole("button", { name: /^views/i });
const open = () => fireEvent.click(trigger());

describe("SavedViews", () => {
  it("toggles a menu with aria-expanded", () => {
    render(<SavedViews ws="w" app="a" search="" onApply={() => {}} />);
    expect(trigger()).toHaveAttribute("aria-haspopup", "menu");
    expect(trigger()).toHaveAttribute("aria-expanded", "false");
    open();
    expect(trigger()).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByLabelText("View name")).toBeInTheDocument();
  });

  it("saves the current search under a typed name with Enter", () => {
    render(<SavedViews ws="w" app="a" search="?sort=loss&sel=x" onApply={() => {}} />);
    open();
    const input = screen.getByLabelText("View name");
    fireEvent.change(input, { target: { value: "by loss" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(listViews("w", "a")).toEqual([{ name: "by loss", search: "?sort=loss" }]);
    expect(screen.getByRole("menuitem", { name: "by loss" })).toBeInTheDocument();
  });

  it("saves with the Save button and ignores an empty name", () => {
    render(<SavedViews ws="w" app="a" search="?q=1" onApply={() => {}} />);
    open();
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(listViews("w", "a")).toEqual([]);
    fireEvent.change(screen.getByLabelText("View name"), { target: { value: "one" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(listViews("w", "a")).toHaveLength(1);
  });

  it("applies a saved view and closes", () => {
    saveView("w", "a", "failed", "?status=failed");
    const onApply = vi.fn();
    render(<SavedViews ws="w" app="a" search="" onApply={onApply} />);
    open();
    fireEvent.click(screen.getByRole("menuitem", { name: "failed" }));
    expect(onApply).toHaveBeenCalledWith("?status=failed");
    expect(screen.queryByLabelText("View name")).toBeNull();
  });

  it("deletes a saved view", () => {
    saveView("w", "a", "old", "?x=1");
    render(<SavedViews ws="w" app="a" search="" onApply={() => {}} />);
    open();
    fireEvent.click(screen.getByRole("button", { name: "Delete view old" }));
    expect(listViews("w", "a")).toEqual([]);
    expect(screen.queryByRole("menuitem", { name: "old" })).toBeNull();
  });

  it("closes on Escape and returns focus to the button", () => {
    render(<SavedViews ws="w" app="a" search="" onApply={() => {}} />);
    open();
    fireEvent.keyDown(screen.getByLabelText("View name"), { key: "Escape" });
    expect(screen.queryByLabelText("View name")).toBeNull();
    expect(trigger()).toHaveFocus();
  });

  it("closes on a click outside", () => {
    render(<div><span>outside</span><SavedViews ws="w" app="a" search="" onApply={() => {}} /></div>);
    open();
    fireEvent.mouseDown(screen.getByText("outside"));
    expect(screen.queryByLabelText("View name")).toBeNull();
  });

  it("shows a hint when nothing is saved yet", () => {
    render(<SavedViews ws="w" app="a" search="" onApply={() => {}} />);
    open();
    expect(screen.getByText(/no saved views/i)).toBeInTheDocument();
  });
});
