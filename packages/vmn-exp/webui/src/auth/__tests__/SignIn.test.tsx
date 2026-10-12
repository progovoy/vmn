import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { createQueryClient } from "../../queryClient";
import { ShellOverrideProvider, useShellOverride } from "../../shell/shellOverride";
import type { Meta } from "../../types";

const meta = vi.fn<() => Promise<Meta>>();
vi.mock("../../api", () => ({ api: { meta: () => meta() } }));

import SignIn from "../SignIn";
import { clearUnauthorized, reportUnauthorized, useAuthState } from "../authState";
import type { AuthHints } from "../../shell/contracts";

const TOKEN = { token: true, oidc: false, login_url: null };
const SSO = { token: false, oidc: true, login_url: "/auth/login" };
const BOTH = { token: true, oidc: true, login_url: "/auth/login" };

function Probe() {
  const override = useShellOverride();
  const { required } = useAuthState();
  return <output data-testid="probe">{`${override ?? "none"} ${required}`}</output>;
}

function renderSignIn(hints: AuthHints | null, path = "/ws/ml/app/my_app?q=metrics.loss%3C1") {
  act(() => reportUnauthorized({ hints, method: "GET" }));
  const client = createQueryClient();
  const invalidate = vi.spyOn(client, "invalidateQueries");
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <ShellOverrideProvider>
          <SignIn />
          <Probe />
        </ShellOverrideProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { invalidate };
}

const submitToken = (value: string) => {
  fireEvent.change(screen.getByLabelText("Token"), { target: { value } });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
};

beforeEach(() => {
  clearUnauthorized();
  meta.mockReset();
});
afterEach(() => {
  vi.unstubAllGlobals();
  sessionStorage.clear();
});

describe("SignIn", () => {
  it("titles the shell sign in and states the server", () => {
    renderSignIn(TOKEN);
    expect(screen.getByRole("heading", { level: 1, name: "Sign in to vmn-exp ui" })).toBeTruthy();
    expect(screen.getByText(`This server at ${window.location.host} requires sign-in.`)).toBeTruthy();
    expect(screen.getByTestId("probe").textContent).toBe("sign-in true");
    expect(document.querySelector(".eyebrow")).toBeNull();
  });

  it("offers a password token field with help", () => {
    renderSignIn(TOKEN);
    const field = screen.getByLabelText("Token") as HTMLInputElement;
    expect(field.type).toBe("password");
    expect(field.getAttribute("autocomplete")).toBe("off");
    expect(field.getAttribute("aria-describedby")).toBeTruthy();
    expect(screen.getByText("The --token / VMN_UI_TOKEN value, or a vmnx_… API token.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Continue with SSO" })).toBeNull();
  });

  it("an accepted token clears the gate and refetches, staying on the route", async () => {
    meta.mockResolvedValue({ version: "1" });
    const { invalidate } = renderSignIn(TOKEN);
    submitToken("vmnx_abc");
    await waitFor(() => expect(screen.getByTestId("probe").textContent).toBe("sign-in false"));
    expect(sessionStorage.getItem("vmn_token")).toBe("vmnx_abc");
    expect(meta).toHaveBeenCalledTimes(1);
    expect(invalidate).toHaveBeenCalled();
  });

  it("a rejected token is removed and explained", async () => {
    meta.mockRejectedValue(Object.assign(new Error("Unauthorized"), { status: 401 }));
    renderSignIn(TOKEN);
    submitToken("wrong");
    expect(await screen.findByText("That token was not accepted.")).toBeTruthy();
    expect(sessionStorage.getItem("vmn_token")).toBeNull();
    expect(screen.getByTestId("probe").textContent).toBe("sign-in true");
  });

  it("a network error says the server is unreachable", async () => {
    meta.mockRejectedValue(new TypeError("Failed to fetch"));
    renderSignIn(TOKEN);
    submitToken("tok");
    expect(await screen.findByText("Can't reach the server.")).toBeTruthy();
    expect(screen.getByTestId("probe").textContent).toBe("sign-in true");
  });

  it("SSO stores the return path and goes to the login URL", () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign, host: window.location.host });
    renderSignIn(SSO);
    expect(screen.queryByLabelText("Token")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Continue with SSO" }));
    expect(sessionStorage.getItem("vmn-exp:return-to")).toBe("/ws/ml/app/my_app?q=metrics.loss%3C1");
    expect(assign).toHaveBeenCalledWith("/auth/login");
  });

  it("with both methods puts SSO first, then the token form", () => {
    renderSignIn(BOTH);
    const sso = screen.getByRole("button", { name: "Continue with SSO" });
    const field = screen.getByLabelText("Token");
    expect(screen.getByText("or paste a token")).toBeTruthy();
    expect(sso.compareDocumentPosition(field) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("an older server without hints gets the token field only", () => {
    renderSignIn(null);
    expect(screen.getByLabelText("Token")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Continue with SSO" })).toBeNull();
    expect(screen.queryByText("or paste a token")).toBeNull();
  });
});
