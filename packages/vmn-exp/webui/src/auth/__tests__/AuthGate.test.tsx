import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { createQueryClient } from "../../queryClient";

vi.mock("../../api", () => ({ api: { meta: vi.fn() } }));

import AuthGate from "../AuthGate";
import { clearUnauthorized, reportUnauthorized } from "../authState";

const HINTS = { token: true, oidc: false, login_url: null };

function renderGate() {
  render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter>
        <AuthGate>
          <label>
            Note
            <input defaultValue="" />
          </label>
        </AuthGate>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => clearUnauthorized());
afterEach(() => sessionStorage.clear());

describe("AuthGate", () => {
  it("renders the page while nothing is required", () => {
    renderGate();
    expect(screen.getByLabelText("Note")).toBeTruthy();
    expect(screen.queryByRole("heading", { name: /sign in/i })).toBeNull();
    expect(screen.queryByRole("region", { name: "Session ended" })).toBeNull();
  });

  it("a GET 401 replaces the page with the sign-in page", () => {
    renderGate();
    act(() => reportUnauthorized({ hints: HINTS, method: "GET" }));
    expect(screen.getByRole("heading", { level: 1, name: "Sign in to vmn-exp ui" })).toBeTruthy();
    expect(screen.queryByLabelText("Note")).toBeNull();

    act(() => clearUnauthorized());
    expect(screen.getByLabelText("Note")).toBeTruthy();
  });

  it("a mutation 401 shows the banner above the page, which stays mounted", () => {
    renderGate();
    const note = screen.getByLabelText("Note") as HTMLInputElement;
    fireEvent.change(note, { target: { value: "half-typed" } });

    act(() => reportUnauthorized({ hints: HINTS, method: "POST" }));
    const banner = screen.getByRole("region", { name: "Session ended" });
    expect(screen.getByLabelText("Note")).toBe(note);
    expect(note.value).toBe("half-typed");
    expect(banner.compareDocumentPosition(note) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.queryByRole("heading", { level: 1, name: "Sign in to vmn-exp ui" })).toBeNull();

    act(() => clearUnauthorized());
    expect(screen.queryByRole("region", { name: "Session ended" })).toBeNull();
    expect((screen.getByLabelText("Note") as HTMLInputElement).value).toBe("half-typed");
  });
});
