import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import ColumnPicker from "../ColumnPicker";

const cells = [
  { kind: "metric" as const, key: "lr" },   // pinned
  { kind: "metric" as const, key: "loss" },  // unpinned
  { kind: "param" as const, key: "batch" },  // unpinned
];

function mkProps(overrides: Partial<Parameters<typeof ColumnPicker>[0]> = {}) {
  return {
    columns: [] as string[], visible: [] as string[], onToggle: vi.fn(),
    orderedCells: cells,
    pinnedCols: ["m:lr"],
    onMoveColumn: vi.fn(),
    onTogglePin: vi.fn(),
    ...overrides,
  };
}

function open() {
  fireEvent.click(screen.getByTitle("Columns"));
}

describe("ColumnPickerOrder — move", () => {
  it("move up calls onMoveColumn with key and -1", () => {
    // batch is index 1 in unpinned group — not first, so up is enabled
    const onMoveColumn = vi.fn();
    render(<ColumnPicker {...mkProps({ onMoveColumn })} />);
    open();
    fireEvent.click(screen.getByRole("button", { name: "Move batch up" }));
    expect(onMoveColumn).toHaveBeenCalledWith("p:batch", -1);
  });

  it("move down calls onMoveColumn with key and +1", () => {
    // loss is index 0 in unpinned group — not last, so down is enabled
    const onMoveColumn = vi.fn();
    render(<ColumnPicker {...mkProps({ onMoveColumn })} />);
    open();
    fireEvent.click(screen.getByRole("button", { name: "Move loss down" }));
    expect(onMoveColumn).toHaveBeenCalledWith("m:loss", 1);
  });

  it("move up disabled for first in its group", () => {
    render(<ColumnPicker {...mkProps()} />);
    open();
    // lr is pinned — first (and only) in the pinned group
    expect(screen.getByRole("button", { name: "Move lr up" })).toBeDisabled();
    // loss is first in the unpinned group
    expect(screen.getByRole("button", { name: "Move loss up" })).toBeDisabled();
  });

  it("move down disabled for last in its group", () => {
    render(<ColumnPicker {...mkProps()} />);
    open();
    // lr is pinned — last (and only) in the pinned group
    expect(screen.getByRole("button", { name: "Move lr down" })).toBeDisabled();
    // batch is last in the unpinned group
    expect(screen.getByRole("button", { name: "Move batch down" })).toBeDisabled();
  });

  it("middle-group buttons are enabled", () => {
    render(<ColumnPicker {...mkProps()} />);
    open();
    expect(screen.getByRole("button", { name: "Move loss down" })).not.toBeDisabled();
    expect(screen.getByRole("button", { name: "Move batch up" })).not.toBeDisabled();
  });
});

describe("ColumnPickerOrder — pin toggle", () => {
  it("pin toggle calls onTogglePin with the full key", () => {
    const onTogglePin = vi.fn();
    render(<ColumnPicker {...mkProps({ onTogglePin })} />);
    open();
    fireEvent.click(screen.getByRole("button", { name: "Pin loss" }));
    expect(onTogglePin).toHaveBeenCalledWith("m:loss");
  });

  it("pinned column's pin button has aria-pressed=true", () => {
    render(<ColumnPicker {...mkProps()} />);
    open();
    expect(screen.getByRole("button", { name: "Pin lr" })).toHaveAttribute("aria-pressed", "true");
  });

  it("unpinned column's pin button has aria-pressed=false", () => {
    render(<ColumnPicker {...mkProps()} />);
    open();
    expect(screen.getByRole("button", { name: "Pin loss" })).toHaveAttribute("aria-pressed", "false");
  });
});

describe("ColumnPickerOrder — visibility", () => {
  it("does not render order section when orderedCells is absent", () => {
    render(<ColumnPicker columns={["lr"]} visible={["lr"]} onToggle={() => {}} />);
    open();
    expect(screen.queryByRole("button", { name: /^Move / })).toBeNull();
  });

  it("renders order section when orderedCells is provided", () => {
    render(<ColumnPicker {...mkProps()} />);
    open();
    expect(screen.getByRole("button", { name: "Move lr up" })).toBeInTheDocument();
  });
});
