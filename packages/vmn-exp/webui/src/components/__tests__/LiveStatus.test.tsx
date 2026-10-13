import { describe, it, expect, vi, afterEach } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import LiveStatus from "../LiveStatus";

afterEach(() => { vi.useRealTimers(); });

function props(extra: Partial<React.ComponentProps<typeof LiveStatus>> = {}) {
  return {
    running: true, paused: false, updatedAt: Date.now(),
    onPause: vi.fn(), onResume: vi.fn(), onRefresh: vi.fn(),
    ...extra,
  };
}

const region = () => document.querySelector("[aria-live='polite']") as HTMLElement;

describe("LiveStatus", () => {
  it("shows live with the data's age and a Pause button while a run is running", () => {
    vi.useFakeTimers();
    const p = props({ updatedAt: Date.now() - 3000 });
    render(<LiveStatus {...p} />);
    expect(screen.getByText(/live · updated 3s ago/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Pause" }));
    expect(p.onPause).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "Refresh" })).toBeNull();
  });

  it("ticks the age every second", () => {
    vi.useFakeTimers();
    render(<LiveStatus {...props({ updatedAt: Date.now() })} />);
    expect(screen.getByText(/updated 0s ago/)).toBeInTheDocument();
    act(() => { vi.advanceTimersByTime(4000); });
    expect(screen.getByText(/updated 4s ago/)).toBeInTheDocument();
  });

  it("offers Resume while paused", () => {
    const p = props({ paused: true });
    render(<LiveStatus {...p} />);
    expect(screen.getByText(/paused · updated/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Pause" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Resume" }));
    expect(p.onResume).toHaveBeenCalledTimes(1);
  });

  it("shows only Refresh with nothing running", () => {
    const p = props({ running: false });
    render(<LiveStatus {...p} />);
    expect(screen.queryByText(/· updated/)).toBeNull();
    expect(screen.queryByRole("button", { name: "Pause" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Resume" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(p.onRefresh).toHaveBeenCalledTimes(1);
  });

  it("announces state changes politely, never the ticking age", () => {
    vi.useFakeTimers();
    const p = props();
    const { rerender } = render(<LiveStatus {...p} />);
    const before = region().textContent;
    expect(before).toMatch(/live updates on/i);
    act(() => { vi.advanceTimersByTime(5000); });
    expect(region().textContent).toBe(before);
    expect(region().textContent).not.toMatch(/ago/);

    rerender(<LiveStatus {...p} paused />);
    expect(region().textContent).toMatch(/paused/i);
    rerender(<LiveStatus {...p} running={false} />);
    expect(region().textContent).toMatch(/nothing running/i);
  });
});
