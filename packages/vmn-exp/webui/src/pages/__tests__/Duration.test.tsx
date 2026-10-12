import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { Duration } from "../RunSections";

/** Return the visible text content for a given duration in seconds. */
const text = (secs: number) => render(<Duration secs={secs} />).container.textContent?.trim();

/** Return the title attribute on the Duration wrapper (exact seconds tooltip). */
const title = (secs: number) => {
  const el = render(<Duration secs={secs} />).container.firstElementChild as HTMLElement;
  return el?.getAttribute("title");
};

describe("Duration component (A5)", () => {
  it("renders 36.6s as '37s' once, not twice", () => {
    const t = text(36.6);
    // Should be a single "37s", not "37s 37s" or "36s 37s"
    expect(t).toBe("37s");
  });

  it("renders 0s as '<1s'", () => {
    expect(text(0)).toBe("<1s");
  });

  it("puts exact seconds in the title attribute for a ladder value", () => {
    // 90s -> "1m" on the ladder, title should contain the exact seconds
    expect(title(90)).toContain("90");
  });

  it("puts exact seconds in the title attribute even for short durations", () => {
    expect(title(36.6)).toContain("37");
  });
});
