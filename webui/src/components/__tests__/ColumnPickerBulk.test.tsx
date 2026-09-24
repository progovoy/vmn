import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import ColumnPicker from "../ColumnPicker";

describe("ColumnPicker bulk actions", () => {
  it("shows only the clicked column, hiding the rest of its section", () => {
    const onToggle = vi.fn();
    render(
      <ColumnPicker
        columns={["lr", "batch", "momentum"]} visible={["lr", "batch", "momentum"]} onToggle={onToggle}
      />,
    );
    fireEvent.click(screen.getByTitle(/columns/i));
    fireEvent.click(screen.getByRole("button", { name: "Show only batch" }));
    expect(onToggle).toHaveBeenCalledWith("lr");
    expect(onToggle).toHaveBeenCalledWith("momentum");
    expect(onToggle).not.toHaveBeenCalledWith("batch");
    expect(onToggle).toHaveBeenCalledTimes(2);
  });

  it("hides every column in a section via Hide all", () => {
    const onToggle = vi.fn();
    render(
      <ColumnPicker columns={["lr", "batch"]} visible={["lr", "batch"]} onToggle={onToggle} />,
    );
    fireEvent.click(screen.getByTitle(/columns/i));
    fireEvent.click(screen.getByRole("button", { name: "Hide all columns" }));
    expect(onToggle).toHaveBeenCalledWith("lr");
    expect(onToggle).toHaveBeenCalledWith("batch");
    expect(onToggle).toHaveBeenCalledTimes(2);
  });

  it("shows every column in a section via Show all", () => {
    const onToggle = vi.fn();
    render(
      <ColumnPicker columns={["lr", "batch"]} visible={[]} onToggle={onToggle} />,
    );
    fireEvent.click(screen.getByTitle(/columns/i));
    fireEvent.click(screen.getByRole("button", { name: "Show all columns" }));
    expect(onToggle).toHaveBeenCalledWith("lr");
    expect(onToggle).toHaveBeenCalledWith("batch");
    expect(onToggle).toHaveBeenCalledTimes(2);
  });

  it("disables Show all once every column is visible, and Hide all once none are", () => {
    render(
      <ColumnPicker columns={["lr", "batch"]} visible={["lr", "batch"]} onToggle={() => {}} />,
    );
    fireEvent.click(screen.getByTitle(/columns/i));
    expect(screen.getByRole("button", { name: "Show all columns" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Hide all columns" })).not.toBeDisabled();
  });

  it("scopes bulk actions to their own section, leaving other sections untouched", () => {
    const onToggle = vi.fn();
    const onToggleMetric = vi.fn();
    render(
      <ColumnPicker
        columns={["lr"]} visible={["lr"]} onToggle={onToggle}
        metricColumns={["loss", "acc"]} visibleMetrics={["loss", "acc"]} onToggleMetric={onToggleMetric}
      />,
    );
    fireEvent.click(screen.getByTitle(/columns/i));
    fireEvent.click(screen.getByRole("button", { name: "Hide all metrics" }));
    expect(onToggleMetric).toHaveBeenCalledWith("loss");
    expect(onToggleMetric).toHaveBeenCalledWith("acc");
    expect(onToggle).not.toHaveBeenCalled();
  });
});
