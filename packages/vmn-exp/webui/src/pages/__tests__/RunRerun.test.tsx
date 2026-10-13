import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { ForkOrigin } from "../RunFork";
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

  it("suggests rerun_of in the query box", () => {
    expect(ROW_FIELDS).toContain("rerun_of");
  });
});
