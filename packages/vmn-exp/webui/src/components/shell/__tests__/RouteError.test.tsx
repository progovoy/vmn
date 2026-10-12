import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import { Outlet, RouterProvider, createMemoryRouter } from "react-router-dom";
import { renderWithClient } from "../../../test-utils";

vi.mock("../../../api", () => ({
  api: { meta: () => Promise.resolve({ version: "1" }), workspaces: () => Promise.resolve([]) },
}));

import RouteError from "../RouteError";

function Thrower({ error }: { error: unknown }): never {
  throw error;
}

function renderWith(error: unknown) {
  const router = createMemoryRouter([
    {
      path: "/",
      element: <div><nav data-testid="sidebar">sidebar</nav><Outlet /></div>,
      children: [
        { path: "page", element: <Thrower error={error} />, errorElement: <RouteError /> },
      ],
    },
  ], { initialEntries: ["/page"] });
  return renderWithClient(<RouterProvider router={router} />);
}

beforeEach(() => {
  vi.spyOn(console, "error").mockImplementation(() => {});
});

describe("RouteError", () => {
  it("renders inside the parent's outlet, so the shell survives", () => {
    renderWith(new Error("kaboom"));
    expect(screen.getByTestId("sidebar")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "This page failed to render" })).toBeInTheDocument();
    expect(screen.getByText("kaboom").tagName).toBe("PRE");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "All workspaces" }).getAttribute("href")).toBe("/");
  });

  it("asks to reload a tab running an older build", () => {
    renderWith(new TypeError("Failed to fetch dynamically imported module: /assets/Run-abc.js"));
    expect(screen.getByRole("heading", { name: "The dashboard was updated" })).toHaveFocus();
    expect(screen.getByText("This tab runs an older build. Reload to load the new one."))
      .toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reload" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
  });

  it("recognises Safari's stale-chunk message too", () => {
    renderWith(new TypeError("Importing a module script failed."));
    expect(screen.getByRole("heading", { name: "The dashboard was updated" })).toBeInTheDocument();
  });

  it("shows a router 404 as a missing page", async () => {
    // The shape isRouteErrorResponse() recognises (a loader's thrown 404, say).
    renderWith({ status: 404, statusText: "Not Found", internal: false, data: null });
    expect(await screen.findByRole("heading", { name: "No page at this address" })).toBeInTheDocument();
    expect(screen.getByText("/page")).toBeInTheDocument();
  });
});
