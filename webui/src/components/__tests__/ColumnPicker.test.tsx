import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import ColumnPicker from "../ColumnPicker";

describe("ColumnPicker", () => {
  it("renders a toggle button", () => {
    render(<ColumnPicker columns={["lr", "batch"]} visible={["lr", "batch"]} onToggle={() => {}} />);
    expect(screen.getByTitle(/columns/i)).toBeInTheDocument();
  });

  it("shows column checkboxes when opened", () => {
    render(<ColumnPicker columns={["lr", "batch"]} visible={["lr", "batch"]} onToggle={() => {}} />);
    fireEvent.click(screen.getByTitle(/columns/i));
    expect(screen.getByLabelText("lr")).toBeInTheDocument();
    expect(screen.getByLabelText("batch")).toBeInTheDocument();
  });

  it("calls onToggle when checkbox is clicked", () => {
    const onToggle = vi.fn();
    render(<ColumnPicker columns={["lr", "batch"]} visible={["lr"]} onToggle={onToggle} />);
    fireEvent.click(screen.getByTitle(/columns/i));
    fireEvent.click(screen.getByLabelText("batch"));
    expect(onToggle).toHaveBeenCalledWith("batch");
  });

  it("checked state reflects visible prop", () => {
    render(<ColumnPicker columns={["lr", "batch"]} visible={["lr"]} onToggle={() => {}} />);
    fireEvent.click(screen.getByTitle(/columns/i));
    expect(screen.getByLabelText("lr")).toBeChecked();
    expect(screen.getByLabelText("batch")).not.toBeChecked();
  });

  it("renders nothing when columns is empty", () => {
    const { container } = render(<ColumnPicker columns={[]} visible={[]} onToggle={() => {}} />);
    expect(container.innerHTML).toBe("");
  });
});
