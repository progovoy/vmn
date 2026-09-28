import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { Duration } from "../RunSections";

const text = (secs: number) => render(<Duration secs={secs} />).container.textContent?.trim();

describe("Run duration", () => {
  it("does not repeat the exact seconds when they match the formatted text", () => {
    expect(text(0)).toBe("0s");
    expect(text(42)).toBe("42s");
  });

  it("adds the exact seconds when the ladder rounds them away", () => {
    expect(text(90)).toBe("1m 90s");
  });
});
