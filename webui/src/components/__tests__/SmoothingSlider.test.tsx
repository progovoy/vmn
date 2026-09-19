import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import SmoothingSlider from "../SmoothingSlider";

describe("SmoothingSlider", () => {
  it("renders a range input with min=0 max=0.99 step=0.01", () => {
    render(<SmoothingSlider value={0} onChange={() => {}} />);
    const slider = screen.getByRole("slider");
    expect(slider).toBeInTheDocument();
    expect(slider).toHaveAttribute("min", "0");
    expect(slider).toHaveAttribute("max", "0.99");
    expect(slider).toHaveAttribute("step", "0.01");
  });

  it("displays current alpha value", () => {
    render(<SmoothingSlider value={0.6} onChange={() => {}} />);
    expect(screen.getByText("0.6")).toBeInTheDocument();
  });

  it("onChange callback fires with new value", () => {
    const onChange = vi.fn();
    render(<SmoothingSlider value={0} onChange={onChange} />);
    fireEvent.change(screen.getByRole("slider"), { target: { value: "0.5" } });
    expect(onChange).toHaveBeenCalledWith(0.5);
  });
});
