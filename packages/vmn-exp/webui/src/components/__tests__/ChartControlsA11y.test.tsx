import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { XModeToggle } from "../ChartControls";

describe("XModeToggle", () => {
  it("marks the current x mode pressed", () => {
    render(<XModeToggle value="wall" onChange={() => {}} timeEnabled />);
    expect(screen.getByRole("button", { name: "Wall" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Step" })).toHaveAttribute("aria-pressed", "false");
  });
});
