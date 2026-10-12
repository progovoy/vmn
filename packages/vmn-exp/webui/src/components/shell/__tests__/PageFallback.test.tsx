import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, render, screen } from "@testing-library/react";
import PageFallback from "../PageFallback";

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("PageFallback", () => {
  it("renders its busy container and status at once", () => {
    const { container } = render(<PageFallback label="experiments" />);
    const box = container.querySelector(".route-fallback");
    expect(box).not.toBeNull();
    expect(box!.getAttribute("aria-busy")).toBe("true");
    expect(screen.getByRole("status").textContent).toBe("Loading experiments…");
    expect(container.querySelector(".skeleton")).toBeNull();
  });

  it("adds the skeleton only after 150 ms, so a fast load doesn't flash", () => {
    const { container } = render(<PageFallback label="run" />);
    act(() => { vi.advanceTimersByTime(140); });
    expect(container.querySelector(".skeleton")).toBeNull();
    act(() => { vi.advanceTimersByTime(20); });
    expect(container.querySelector(".route-fallback .skeleton")).not.toBeNull();
    expect(container.querySelector(".route-fallback .fallback-head")).not.toBeNull();
  });
});
