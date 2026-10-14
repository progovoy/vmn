/** The outer run's page header carries the `outer · N runs` badge. */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import JobHeader from "../JobHeader";
import { jobSummaryFixture } from "./jobFixture";

describe("the outer run's header", () => {
  it("badges the title with the subtree's run count", () => {
    render(<JobHeader summary={jobSummaryFixture()} actions={null} />);
    const title = screen.getByRole("heading", { level: 1 }).parentElement as HTMLElement;
    expect(title.querySelector(".outer-badge")).toHaveTextContent("outer · 2,000 runs");
  });
});
