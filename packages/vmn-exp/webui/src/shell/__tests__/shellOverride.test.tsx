import { describe, it, expect } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { ShellOverrideProvider, useOverrideRoute, useShellOverride } from "../shellOverride";

function Probe() {
  return <span data-testid="override">{useShellOverride() ?? "none"}</span>;
}
function Sets({ id }: { id: "not-found" | "sign-in" }) {
  useOverrideRoute(id);
  return <span>child</span>;
}
function Harness() {
  const [on, setOn] = useState(true);
  return (
    <ShellOverrideProvider>
      <Probe />
      {on && <Sets id="not-found" />}
      <button onClick={() => setOn(false)}>unmount</button>
    </ShellOverrideProvider>
  );
}

describe("shellOverride", () => {
  it("sets the override on mount and clears it on unmount", () => {
    render(<Harness />);
    expect(screen.getByTestId("override")).toHaveTextContent("not-found");
    fireEvent.click(screen.getByText("unmount"));
    expect(screen.getByTestId("override")).toHaveTextContent("none");
  });

  it("is a no-op without a provider", () => {
    render(<><Probe /><Sets id="sign-in" /></>);
    expect(screen.getByText("child")).toBeInTheDocument();
    expect(screen.getByTestId("override")).toHaveTextContent("none");
  });
});
