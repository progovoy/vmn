/** A stand-in for uPlot in jsdom (no canvas): records what it was built with
 *  and lets a test drive the cursor hook. Use via
 *  `vi.mock("uplot", async () => await import("./fakeUPlot"))`. */
import { vi } from "vitest";

type Opts = {
  hooks?: { setCursor?: ((u: FakeUPlot) => void)[] };
  [k: string]: unknown;
};

export const instances: FakeUPlot[] = [];

export default class FakeUPlot {
  opts: Opts;
  data: unknown;
  el: HTMLElement;
  cursor = { left: -10, top: -10 };
  destroyed = false;
  setData = vi.fn();
  setSize = vi.fn();
  setSeries = vi.fn();

  constructor(opts: Opts, data: unknown, el: HTMLElement) {
    this.opts = opts;
    this.data = data;
    this.el = el;
    instances.push(this);
  }

  /** Pixel -> value is the identity, so a test picks values directly. */
  posToVal(px: number) {
    return px;
  }

  destroy() {
    this.destroyed = true;
  }

  moveCursor(left: number, top: number) {
    this.cursor = { left, top };
    for (const h of this.opts.hooks?.setCursor ?? []) h(this);
  }
}

/** jsdom has neither matchMedia nor a 2d context; pretend it does. */
export function enableCanvas() {
  window.matchMedia = vi.fn().mockReturnValue({
    matches: false, addEventListener() {}, removeEventListener() {},
  }) as unknown as typeof window.matchMedia;
  HTMLCanvasElement.prototype.getContext = vi.fn().mockReturnValue({}) as never;
}

export function resetInstances() {
  instances.length = 0;
}
