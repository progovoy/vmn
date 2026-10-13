import { describe, it, expect, vi, afterEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import SearchButton from "../SearchButton";
import { TOUCH_QUERY } from "../../../hooks/useMediaQuery";
import { dropFakeMedia, fakeMedia } from "../../../hooks/__tests__/fakeMedia";

const setPlatform = (value: string) =>
  Object.defineProperty(navigator, "platform", { value, configurable: true });

describe("SearchButton", () => {
  afterEach(() => setPlatform(""));

  it("reads Search with a ⌘K key cap on a Mac", () => {
    setPlatform("MacIntel");
    render(<SearchButton onSearch={() => {}} />);
    const btn = screen.getByRole("button", { name: "Search (⌘K)" });
    expect(btn).toHaveClass("search-btn");
    expect(btn.textContent).toBe("Search⌘K");
    expect(btn.querySelector(".search-key")!.textContent).toBe("⌘K");
    expect(btn.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
  });

  it("reads Ctrl K elsewhere", () => {
    setPlatform("Linux x86_64");
    render(<SearchButton onSearch={() => {}} />);
    expect(screen.getByRole("button", { name: "Search (Ctrl K)" }).textContent).toBe("SearchCtrl K");
  });

  it("calls onSearch on click", () => {
    const onSearch = vi.fn();
    render(<SearchButton onSearch={onSearch} />);
    fireEvent.click(screen.getByRole("button", { name: /^Search/ }));
    expect(onSearch).toHaveBeenCalledOnce();
  });

  it("shows no key cap on a touch screen, where there is no keyboard to press it on", () => {
    setPlatform("iPhone");
    fakeMedia([TOUCH_QUERY]);
    try {
      render(<SearchButton onSearch={() => {}} />);
      const btn = screen.getByRole("button", { name: "Search" });
      expect(btn.querySelector(".search-key")).toBeNull();
      expect(btn.textContent).toBe("Search");
    } finally {
      dropFakeMedia();
    }
  });
});
