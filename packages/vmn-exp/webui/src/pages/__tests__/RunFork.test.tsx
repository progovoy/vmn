import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { ForkOrigin } from "../RunFork";

const runUrl = (v: string) => `/ws/main/app/demo/run/${encodeURIComponent(v)}`;

describe("ForkOrigin", () => {
  it("links a fork to its source run and step", () => {
    render(
      <MemoryRouter>
        <ForkOrigin forkedFrom={{ verstr: "0.0.1-dev.a", step: 200 }} rewinds={[]} runUrl={runUrl} />
      </MemoryRouter>,
    );
    const link = screen.getByRole("link", { name: "0.0.1-dev.a" });
    expect(link).toHaveAttribute("href", "/ws/main/app/demo/run/0.0.1-dev.a");
    expect(screen.getByTestId("fork-origin").textContent).toBe("forked from 0.0.1-dev.a @ step 200");
  });

  it("lists a run's rewinds", () => {
    render(
      <MemoryRouter>
        <ForkOrigin forkedFrom={null}
          rewinds={[{ step: 3, timestamp: "2026-01-01T00:00:00Z" }, { step: 1, timestamp: null }]}
          runUrl={runUrl} />
      </MemoryRouter>,
    );
    expect(screen.getByTestId("run-rewinds").textContent).toBe("rewound to step 3, then to step 1");
  });

  it("renders nothing for a plain run", () => {
    const { container } = render(
      <MemoryRouter><ForkOrigin forkedFrom={null} rewinds={[]} runUrl={runUrl} /></MemoryRouter>,
    );
    expect(container.firstChild).toBeNull();
  });
});
