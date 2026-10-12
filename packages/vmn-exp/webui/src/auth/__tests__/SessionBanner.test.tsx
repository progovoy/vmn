import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, render, screen } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { createQueryClient } from "../../queryClient";
import { ShellOverrideProvider, useShellOverride } from "../../shell/shellOverride";

vi.mock("../../api", () => ({ api: { meta: vi.fn() } }));

import SessionBanner from "../SessionBanner";
import { clearUnauthorized, reportUnauthorized } from "../authState";

function Probe() {
  return <output data-testid="probe">{useShellOverride() ?? "none"}</output>;
}

function renderBanner() {
  act(() => reportUnauthorized({ hints: { token: true, oidc: false, login_url: null }, method: "POST" }));
  render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter>
        <ShellOverrideProvider>
          <SessionBanner />
          <Probe />
        </ShellOverrideProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => clearUnauthorized());

describe("SessionBanner", () => {
  it("is a region named by its heading, and the heading takes focus", () => {
    renderBanner();
    const heading = screen.getByRole("heading", { level: 2, name: "Session ended" });
    expect(screen.getByRole("region", { name: "Session ended" })).toBeTruthy();
    expect(document.activeElement).toBe(heading);
  });

  it("says nothing was lost and embeds the compact sign-in form", () => {
    renderBanner();
    expect(screen.getByText(
      "Sign in again to continue. Nothing on this page was lost. The action you tried was not sent; retry it after signing in.",
    )).toBeTruthy();
    expect(screen.getByLabelText("Token")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Sign in" })).toBeTruthy();
    expect(screen.queryByRole("heading", { level: 1 })).toBeNull();
  });

  it("does not retitle the shell: the page is still there", () => {
    renderBanner();
    expect(screen.getByTestId("probe").textContent).toBe("none");
  });
});
