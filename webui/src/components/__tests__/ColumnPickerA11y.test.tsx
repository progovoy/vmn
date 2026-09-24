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
