import { describe, it, expect, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import ThemeToggle from "../ThemeToggle";

beforeEach(() => {
  localStorage.clear();
  delete document.documentElement.dataset.theme;
});

describe("ThemeToggle", () => {
  it("names the current mode and cycles through the three", () => {
    render(<ThemeToggle />);
    const btn = screen.getByRole("button", { name: /theme/i });
    expect(btn).toHaveAttribute("title", expect.stringMatching(/system/i));
    fireEvent.click(btn);
    expect(btn).toHaveAttribute("title", expect.stringMatching(/light/i));
    expect(document.documentElement.dataset.theme).toBe("light");
    fireEvent.click(btn);
    expect(btn).toHaveAttribute("title", expect.stringMatching(/dark/i));
    expect(document.documentElement.dataset.theme).toBe("dark");
    fireEvent.click(btn);
    expect(btn).toHaveAttribute("title", expect.stringMatching(/system/i));
    expect(document.documentElement.dataset.theme).toBeUndefined();
  });

  it("restores the persisted choice", () => {
    localStorage.setItem("vmn_theme", "dark");
    render(<ThemeToggle />);
    expect(screen.getByRole("button", { name: /theme/i }))
      .toHaveAttribute("title", expect.stringMatching(/dark/i));
  });
});
