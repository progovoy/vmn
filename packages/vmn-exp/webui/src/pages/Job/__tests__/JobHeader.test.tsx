/** Plan 23 §3.2 polish: the job header is a grid of three rows — title and
 *  actions on one, the full-width progress, then (outside it) the tabs. */
import { describe, it, expect, beforeAll } from "vitest";
import { render, screen } from "@testing-library/react";
import JobHeader from "../JobHeader";
import { jobSummaryFixture } from "./jobFixture";

type Fs = { readFileSync(path: string, encoding: "utf8"): string };
let css = "";
beforeAll(async () => {
  const fs: Fs = await import(/* @vite-ignore */ "node:fs" as string);
  css = fs.readFileSync("src/pages/Job/job.css", "utf8");
});

function rule(selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = css.match(new RegExp(`(^|\\})\\s*${escaped}\\s*\\{([^}]*)\\}`, "m"));
  expect(match, `rule ${selector}`).not.toBeNull();
  return match![2];
}

describe("the job header", () => {
  it("puts the title, the actions and the progress straight in one grid, in that order", () => {
    render(<JobHeader summary={jobSummaryFixture()} actions={<button type="button">Reproduce</button>} />);
    const header = screen.getByRole("banner");
    expect(header).toHaveClass("job-header");
    // styles.css's `.job-head` (the job card) is a flex row; the page header never shares it.
    expect(header).not.toHaveClass("job-head");
    expect([...header.children].map((c) => c.className))
      .toEqual(["job-title", "job-actions", "job-head-progress"]);
  });

  it("lays the title and actions on row 1 and the progress across row 2", () => {
    const header = rule(".job-header");
    expect(header).toMatch(/display:\s*grid/);
    expect(header).toMatch(/grid-template-areas:\s*"title actions"\s*"progress progress"/);
    expect(rule(".job-title")).toMatch(/grid-area:\s*title/);
    expect(rule(".job-actions")).toMatch(/grid-area:\s*actions/);
    expect(rule(".job-head-progress")).toMatch(/grid-area:\s*progress/);
  });
});
