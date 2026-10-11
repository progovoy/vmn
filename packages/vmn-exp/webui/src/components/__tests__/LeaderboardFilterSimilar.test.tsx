import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import LeaderboardFilter from "../LeaderboardFilter";

const toggle = () => screen.getByRole("button", { name: /^similar$/i });
const box = () => screen.getByRole("textbox", { name: /search runs/i });
const settle = () => act(() => { vi.advanceTimersByTime(400); });

describe("LeaderboardFilter similar mode", () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); });

  it("offers the toggle only to a board that handles it", () => {
    const { rerender } = render(<LeaderboardFilter />);
    expect(screen.queryByRole("button", { name: /^similar$/i })).toBeNull();
    rerender(<LeaderboardFilter onSimilarChange={vi.fn()} />);
    expect(toggle()).toHaveAttribute("aria-pressed", "false");
  });

  it("sends the box text as a similar-runs text, not as a search", () => {
    const onSearchChange = vi.fn();
    const onSimilarChange = vi.fn();
    render(<LeaderboardFilter onSearchChange={onSearchChange} onSimilarChange={onSimilarChange} />);
    settle();
    onSearchChange.mockClear();
    fireEvent.click(toggle());
    expect(toggle()).toHaveAttribute("aria-pressed", "true");
    expect(box().getAttribute("placeholder")).toMatch(/describe/i);
    fireEvent.change(box(), { target: { value: "  focal loss " } });
    expect(onSimilarChange).not.toHaveBeenCalledWith("focal loss");
    settle();
    expect(onSimilarChange).toHaveBeenLastCalledWith("focal loss");
    expect(onSearchChange).not.toHaveBeenCalledWith("focal loss");
  });

  it("leaving the mode restores the search the box held", () => {
    const onSearchChange = vi.fn();
    const onSimilarChange = vi.fn();
    render(<LeaderboardFilter onSearchChange={onSearchChange} onSimilarChange={onSimilarChange} />);
    fireEvent.change(box(), { target: { value: "batch" } });
    settle();
    fireEvent.click(toggle());
    expect(box()).toHaveValue("");
    fireEvent.change(box(), { target: { value: "label smoothing" } });
    settle();
    fireEvent.click(toggle());
    expect(onSimilarChange).toHaveBeenLastCalledWith(null);
    expect(box()).toHaveValue("batch");
    expect(onSearchChange).toHaveBeenLastCalledWith("batch");
  });

  it("keeps the query box in either mode", () => {
    render(<LeaderboardFilter onSimilarChange={vi.fn()} />);
    fireEvent.click(toggle());
    expect(screen.getByPlaceholderText(/metrics\./i)).toBeInTheDocument();
  });
});
