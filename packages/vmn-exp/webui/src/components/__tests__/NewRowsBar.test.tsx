import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, renderHook, screen } from "@testing-library/react";
import { useRef } from "react";
import NewRowsBar, { useHeldViewport } from "../NewRowsBar";
import type { BoardViewport } from "../../hooks/useLeaderboardRows";

describe("NewRowsBar (plan 23 W6)", () => {
  it("says how many new runs wait and shows them on click", () => {
    const onShow = vi.fn();
    render(<NewRowsBar pending={{ added: 12, reordered: true }} onShow={onShow} />);
    fireEvent.click(screen.getByRole("button", { name: "12 new runs · show" }));
    expect(onShow).toHaveBeenCalledTimes(1);
  });

  it("names a reorder without new runs, a job noun, and nothing when none wait", () => {
    const { rerender, container } = render(
      <NewRowsBar pending={{ added: 0, reordered: true }} onShow={() => {}} />,
    );
    expect(screen.getByRole("button").textContent).toBe("Order changed · show");
    rerender(<NewRowsBar pending={{ added: 1, reordered: false }} noun="job" onShow={() => {}} />);
    expect(screen.getByRole("button").textContent).toBe("1 new job · show");
    rerender(<NewRowsBar pending={null} onShow={() => {}} />);
    expect(container.textContent).toBe("");
  });
});

describe("useHeldViewport", () => {
  function mount(selected: ReadonlySet<string>, el: HTMLElement | null) {
    return renderHook(() => {
      const viewport = useRef<BoardViewport>({ held: () => false, toTop: () => {} });
      const scroller = useRef<HTMLElement | null>(el);
      useHeldViewport(viewport, scroller, selected);
      return viewport;
    }).result.current;
  }

  it("holds while scrolled down or with rows selected, and scrolls back to the top", () => {
    const el = document.createElement("div");
    expect(mount(new Set(), el).current.held()).toBe(false);
    expect(mount(new Set(["a"]), el).current.held()).toBe(true);
    const viewport = mount(new Set(), el);
    el.scrollTop = 120;
    expect(viewport.current.held()).toBe(true);
    viewport.current.toTop();
    expect(el.scrollTop).toBe(0);
  });

  it("reads the window's scroll without a scroll element (the phone's cards)", () => {
    const viewport = mount(new Set(), null);
    Object.defineProperty(window, "scrollY", { configurable: true, value: 300 });
    expect(viewport.current.held()).toBe(true);
    const scrollTo = vi.spyOn(window, "scrollTo").mockImplementation(() => {});
    viewport.current.toTop();
    expect(scrollTo).toHaveBeenCalledWith(0, 0);
    Object.defineProperty(window, "scrollY", { configurable: true, value: 0 });
  });
});
