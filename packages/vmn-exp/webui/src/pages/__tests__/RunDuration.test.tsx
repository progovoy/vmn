import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { Duration } from "../RunSections";

const text = (secs: number) => render(<Duration secs={secs} />).container.textContent?.trim();
const title = (secs: number) => {
  const el = render(<Duration secs={secs} />).container.firstElementChild as HTMLElement;
  return el?.getAttribute("title");
};

describe("Run duration", () => {
  it("shows <1s for zero and the rounded value for short durations", () => {
    expect(text(0)).toBe("<1s");
    expect(text(42)).toBe("42s");
  });

  it("shows the ladder text for durations above 60s, with exact seconds in title", () => {
    expect(text(90)).toBe("1m");
    expect(title(90)).toBe("90s");
  });
});
