import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
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

  describe("states the resolved mode", () => {
    const prefersDark = (dark: boolean) =>
      vi.stubGlobal("matchMedia", (q: string) => ({
        matches: q.includes("dark") ? dark : !dark, media: q,
        addEventListener: () => {}, removeEventListener: () => {},
      }));
    afterEach(() => vi.unstubAllGlobals());

    it("names the system mode it resolves to and the next one", () => {
      prefersDark(true);
      render(<ThemeToggle />);
      const btn = screen.getByRole("button", { name: "Theme: system (dark). Switch to light" });
      expect(btn).toHaveAttribute("title", "Theme: system (dark). Switch to light");
      fireEvent.click(btn);
      expect(btn).toHaveAccessibleName("Theme: light. Switch to dark");
      expect(btn).toHaveAttribute("title", "Theme: light. Switch to dark");
      fireEvent.click(btn);
      expect(btn).toHaveAccessibleName("Theme: dark. Switch to system");
    });

    it("reads system (light) under a light OS palette", () => {
      prefersDark(false);
      render(<ThemeToggle />);
      expect(screen.getByRole("button", { name: "Theme: system (light). Switch to light" }))
        .toBeInTheDocument();
    });

    it("draws an SVG icon, never a unicode glyph", () => {
      render(<ThemeToggle />);
      const btn = screen.getByRole("button", { name: /theme/i });
      for (let i = 0; i < 3; i++) {
        expect(btn.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
        expect(btn.textContent).not.toMatch(/[◐☀☾]/);
        fireEvent.click(btn);
      }
    });
  });
});
