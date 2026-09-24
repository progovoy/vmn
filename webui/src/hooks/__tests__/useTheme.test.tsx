import { describe, it, expect, beforeEach } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { nextTheme, THEME_EVENT, THEME_KEY, useTheme, useThemeVersion } from "../useTheme";

beforeEach(() => {
  localStorage.clear();
  delete document.documentElement.dataset.theme;
});

describe("useTheme", () => {
  it("defaults to following the system, with no data-theme set", () => {
    const { result } = renderHook(() => useTheme());
    expect(result.current[0]).toBe("system");
    expect(document.documentElement.dataset.theme).toBeUndefined();
  });

  it("starts from the stored preference and applies it", () => {
    localStorage.setItem(THEME_KEY, "light");
    const { result } = renderHook(() => useTheme());
    expect(result.current[0]).toBe("light");
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("ignores a garbage stored value", () => {
    localStorage.setItem(THEME_KEY, "purple");
    const { result } = renderHook(() => useTheme());
    expect(result.current[0]).toBe("system");
  });

  it("persists and applies a new choice; system removes the attribute", () => {
    const { result } = renderHook(() => useTheme());
    act(() => result.current[1]("dark"));
    expect(localStorage.getItem(THEME_KEY)).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
    act(() => result.current[1]("system"));
    expect(localStorage.getItem(THEME_KEY)).toBe("system");
    expect(document.documentElement.dataset.theme).toBeUndefined();
  });

  it("cycles system -> light -> dark -> system", () => {
    expect(nextTheme("system")).toBe("light");
    expect(nextTheme("light")).toBe("dark");
    expect(nextTheme("dark")).toBe("system");
  });
});

describe("useThemeVersion", () => {
  it("bumps when the theme changes, so charts re-read their colours", () => {
    const { result } = renderHook(() => useThemeVersion());
    const before = result.current;
    act(() => { window.dispatchEvent(new Event(THEME_EVENT)); });
    expect(result.current).toBe(before + 1);
  });

  it("bumps on a theme set through useTheme", () => {
    const version = renderHook(() => useThemeVersion());
    const theme = renderHook(() => useTheme());
    const before = version.result.current;
    act(() => theme.result.current[1]("light"));
    expect(version.result.current).toBeGreaterThan(before);
  });
});
