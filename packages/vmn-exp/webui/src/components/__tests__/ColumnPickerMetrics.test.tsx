import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import ColumnPicker from "../ColumnPicker";

describe("ColumnPicker metric columns", () => {
  it("lists metric columns in their own section and toggles them", () => {
    const onToggleMetric = vi.fn();
    render(
      <ColumnPicker
        columns={["lr"]} visible={["lr"]} onToggle={() => {}}
        metricColumns={["loss", "acc"]} visibleMetrics={["loss"]}
        onToggleMetric={onToggleMetric}
      />,
    );
    fireEvent.click(screen.getByTitle(/columns/i));
    expect(screen.getByText("metrics")).toBeInTheDocument();
    expect(screen.getByLabelText("loss")).toBeChecked();
    expect(screen.getByLabelText("acc")).not.toBeChecked();
    fireEvent.click(screen.getByLabelText("acc"));
    expect(onToggleMetric).toHaveBeenCalledWith("acc");
  });

  it("renders with metrics even when there are no params", () => {
    render(
      <ColumnPicker
        columns={[]} visible={[]} onToggle={() => {}}
        metricColumns={["loss"]} visibleMetrics={["loss"]} onToggleMetric={() => {}}
      />,
    );
    expect(screen.getByTitle(/columns/i)).toBeInTheDocument();
  });

  it("filters the list by the typed text", () => {
    render(
      <ColumnPicker
        columns={["lr", "batch"]} visible={["lr", "batch"]} onToggle={() => {}}
        metricColumns={["loss", "val_loss"]} visibleMetrics={[]} onToggleMetric={() => {}}
      />,
    );
    fireEvent.click(screen.getByTitle(/columns/i));
    fireEvent.change(screen.getByLabelText("Filter columns"), { target: { value: "loss" } });
    expect(screen.getByLabelText("loss")).toBeInTheDocument();
    expect(screen.getByLabelText("val_loss")).toBeInTheDocument();
    expect(screen.queryByLabelText("lr")).toBeNull();
    expect(screen.queryByLabelText("batch")).toBeNull();
  });
});
