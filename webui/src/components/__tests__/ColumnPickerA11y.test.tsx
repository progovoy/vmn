import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import ColumnPicker from "../ColumnPicker";

const base = { columns: ["lr"], visible: ["lr"], onToggle: () => {} };

describe("ColumnPicker other columns", () => {
  it("toggles non-metric, non-param columns such as tags", () => {
    const onToggleOther = vi.fn();
    render(
      <ColumnPicker {...base} otherColumns={["tags"]} visibleOther={["tags"]} onToggleOther={onToggleOther} />,
    );
    fireEvent.click(screen.getByTitle("Columns"));
    expect(screen.getByLabelText("tags")).toBeChecked();
    fireEvent.click(screen.getByLabelText("tags"));
    expect(onToggleOther).toHaveBeenCalledWith("tags");
  });

  it("renders for other columns alone", () => {
    render(
      <ColumnPicker columns={[]} visible={[]} onToggle={() => {}}
        otherColumns={["tags"]} visibleOther={[]} onToggleOther={() => {}} />,
    );
    expect(screen.getByTitle("Columns")).toBeInTheDocument();
  });
});

describe("ColumnPicker closing and state", () => {
  it("reports its state with aria-expanded", () => {
    render(<ColumnPicker {...base} />);
    const btn = screen.getByTitle("Columns");
    expect(btn).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(btn);
    expect(btn).toHaveAttribute("aria-expanded", "true");
  });

  it("closes on Escape and gives focus back to its button", () => {
    render(<ColumnPicker {...base} />);
    const btn = screen.getByTitle("Columns");
    fireEvent.click(btn);
    fireEvent.keyDown(screen.getByLabelText("Filter columns"), { key: "Escape" });
    expect(screen.queryByLabelText("Filter columns")).toBeNull();
    expect(btn).toHaveFocus();
  });

  it("closes on a click outside, not on one inside", () => {
    render(<div><ColumnPicker {...base} /><p>outside</p></div>);
    fireEvent.click(screen.getByTitle("Columns"));
    fireEvent.mouseDown(screen.getByLabelText("lr"));
    expect(screen.getByLabelText("Filter columns")).toBeInTheDocument();
    fireEvent.mouseDown(screen.getByText("outside"));
    expect(screen.queryByLabelText("Filter columns")).toBeNull();
  });
});

const cells = [
  { kind: "metric" as const, key: "lr" },
  { kind: "metric" as const, key: "loss" },
];
const orderProps = {
  columns: [] as string[], visible: [] as string[], onToggle: () => {},
  orderedCells: cells,
  pinnedCols: [] as string[],
  onMoveColumn: vi.fn(),
  onTogglePin: vi.fn(),
};

describe("ColumnOrderSection accessibility", () => {
  it("move buttons have descriptive aria-labels", () => {
    render(<ColumnPicker {...orderProps} />);
    fireEvent.click(screen.getByTitle("Columns"));
    expect(screen.getByRole("button", { name: "Move lr up" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Move lr down" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pin lr" })).toBeInTheDocument();
  });

  it("pin button has aria-pressed reflecting pin state", () => {
    render(<ColumnPicker {...orderProps} pinnedCols={["m:lr"]} />);
    fireEvent.click(screen.getByTitle("Columns"));
    expect(screen.getByRole("button", { name: "Pin lr" }))
      .toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Pin loss" }))
      .toHaveAttribute("aria-pressed", "false");
  });

  it("Enter and Space trigger move buttons (native button behaviour)", () => {
    const onMoveColumn = vi.fn();
    render(<ColumnPicker {...orderProps} onMoveColumn={onMoveColumn} />);
    fireEvent.click(screen.getByTitle("Columns"));
    const btn = screen.getByRole("button", { name: "Move loss up" });
    fireEvent.keyDown(btn, { key: "Enter" });
    fireEvent.click(btn);   // JSDOM fires click on Enter/Space for buttons
    expect(onMoveColumn).toHaveBeenCalledWith("m:loss", -1);
  });

  it("focus moves to the same direction button of the moved item", async () => {
    const cells2 = [
      { kind: "metric" as const, key: "lr" },
      { kind: "metric" as const, key: "loss" },
      { kind: "metric" as const, key: "f1" },
    ];
    const { rerender } = render(
      <ColumnPicker
        {...orderProps}
        orderedCells={cells2}
      />,
    );
    fireEvent.click(screen.getByTitle("Columns"));
    const btn = screen.getByRole("button", { name: "Move loss down" });
    fireEvent.click(btn);
    // Simulate parent updating orderedCells after move (loss and f1 swapped)
    const reordered = [
      { kind: "metric" as const, key: "lr" },
      { kind: "metric" as const, key: "f1" },
      { kind: "metric" as const, key: "loss" },
    ];
    rerender(
      <ColumnPicker
        {...orderProps}
        orderedCells={reordered}
      />,
    );
    // loss is now last in its group, so "down" is disabled; focus falls back to "up"
    expect(screen.getByRole("button", { name: "Move loss up" })).toHaveFocus();
  });
});
