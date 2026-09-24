import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import ErrorBoundary from "../ErrorBoundary";

function Boom({ fail }: { fail: boolean }) {
  if (fail) throw new Error("kaboom");
  return <div>fine</div>;
}

describe("ErrorBoundary resetKey", () => {
  it("clears the error when the reset key changes", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const { rerender } = render(
      <ErrorBoundary resetKey="/a"><Boom fail /></ErrorBoundary>,
    );
    expect(screen.getByRole("alert")).toBeInTheDocument();
    rerender(<ErrorBoundary resetKey="/b"><Boom fail={false} /></ErrorBoundary>);
    expect(screen.getByText("fine")).toBeInTheDocument();
  });

  it("keeps showing the error while the key stays the same", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const { rerender } = render(
      <ErrorBoundary resetKey="/a"><Boom fail /></ErrorBoundary>,
    );
    rerender(<ErrorBoundary resetKey="/a"><Boom fail={false} /></ErrorBoundary>);
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });
});
