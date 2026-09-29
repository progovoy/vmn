import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { ForkOrigin } from "../RunFork";
import { RerunHints } from "../RunRerun";
import { ROW_FIELDS } from "../../util/querySuggest";

const runUrl = (v: string) => `/ws/main/app/demo/run/${encodeURIComponent(v)}`;

describe("rerun links", () => {
  it("links a rerun to the run it reran", () => {
    render(
      <MemoryRouter>
        <ForkOrigin forkedFrom={null} rerunOf="0.0.1-dev.a" rewinds={[]} runUrl={runUrl} />
      </MemoryRouter>,
    );
    const link = screen.getByRole("link", { name: "0.0.1-dev.a" });
    expect(link).toHaveAttribute("href", "/ws/main/app/demo/run/0.0.1-dev.a");
    expect(screen.getByTestId("rerun-of").textContent).toBe("rerun of 0.0.1-dev.a");
  });

  it("offers the rerun command and a leaderboard of the run's reruns", () => {
    render(
      <MemoryRouter>
        <RerunHints boardBase="/ws/main/app/demo" appName="demo" verstr="0.0.1-dev.a"
          command={["python", "train.py"]} />
      </MemoryRouter>,
    );
    expect(screen.getByText("vmn-exp rerun demo -v 0.0.1-dev.a")).toBeInTheDocument();
    const reruns = screen.getByRole("link", { name: "reruns →" });
    expect(reruns).toHaveAttribute(
      "href", `/ws/main/app/demo?q=${encodeURIComponent('rerun_of = "0.0.1-dev.a"')}`,
    );
  });

  it("has no rerun hint for a run that recorded no command", () => {
    const { container } = render(
      <MemoryRouter>
        <RerunHints boardBase="/ws/main/app/demo" appName="demo" verstr="v" command={null} />
      </MemoryRouter>,
    );
    expect(container.firstChild).toBeNull();
  });

  it("suggests rerun_of in the query box", () => {
    expect(ROW_FIELDS).toContain("rerun_of");
  });
});
