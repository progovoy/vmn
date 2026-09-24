import { describe, it, expect, afterEach } from "vitest";
import { act, render, screen } from "@testing-library/react";
import LazyMount from "../LazyMount";

type Cb = (entries: { isIntersecting: boolean }[]) => void;
const observers: { cb: Cb; disconnected: boolean }[] = [];

class FakeIO {
  entry: { cb: Cb; disconnected: boolean };
  constructor(cb: Cb) {
    this.entry = { cb, disconnected: false };
    observers.push(this.entry);
  }
  observe() {}
  disconnect() { this.entry.disconnected = true; }
}

const original = globalThis.IntersectionObserver;
afterEach(() => {
  globalThis.IntersectionObserver = original;
  observers.length = 0;
});

describe("LazyMount", () => {
  it("renders children straight away without IntersectionObserver", () => {
    // jsdom ships none
    delete (globalThis as { IntersectionObserver?: unknown }).IntersectionObserver;
    render(<LazyMount height={100}><span>chart</span></LazyMount>);
    expect(screen.getByText("chart")).toBeInTheDocument();
  });

  it("holds a same-height placeholder until scrolled into view", () => {
    globalThis.IntersectionObserver = FakeIO as unknown as typeof IntersectionObserver;
    const { container } = render(<LazyMount height={120}><span>chart</span></LazyMount>);
    expect(screen.queryByText("chart")).toBeNull();
    expect((container.firstChild as HTMLElement).style.minHeight).toBe("120px");

    act(() => observers[0].cb([{ isIntersecting: true }]));
    expect(screen.getByText("chart")).toBeInTheDocument();
    expect(observers[0].disconnected).toBe(true);
  });

  it("ignores notifications that are not intersecting", () => {
    globalThis.IntersectionObserver = FakeIO as unknown as typeof IntersectionObserver;
    render(<LazyMount height={120}><span>chart</span></LazyMount>);
    act(() => observers[0].cb([{ isIntersecting: false }]));
    expect(screen.queryByText("chart")).toBeNull();
  });
});
