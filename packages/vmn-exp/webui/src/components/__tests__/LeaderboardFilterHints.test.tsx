import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import LeaderboardFilter from "../LeaderboardFilter";

const HINT = 'kind = "launch" matches nothing; did you mean tags.kind?';

describe("LeaderboardFilter query hints (plan 31 §4.2)", () => {
  it("shows the server's hints under the query bar", () => {
    render(<LeaderboardFilter queryHints={[HINT]} />);
    expect(screen.getByText(HINT)).toHaveClass("query-note");
  });

  it("shows nothing without hints", () => {
    const { container } = render(<LeaderboardFilter queryHints={[]} />);
    expect(container.querySelector(".query-note")).toBeNull();
  });
});
