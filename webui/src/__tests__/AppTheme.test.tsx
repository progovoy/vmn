import { describe, it, expect, vi, beforeAll, afterAll } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router-dom";

vi.mock("../api", () => ({
  api: { workspaces: vi.fn(() => Promise.resolve([])), meta: vi.fn(() => Promise.resolve({ version: "1" })), apps: vi.fn() },
  appName: (t: string) => t.replaceAll("-", "/"),
  appTag: (n: string) => n.replaceAll("/", "-"),
}));

import App from "../App";
import { createQueryClient } from "../queryClient";

// Node's Request rejects jsdom's AbortSignal (see AppShell.test.tsx).
const NodeRequest = globalThis.Request;
beforeAll(() => {
  globalThis.Request = class extends NodeRequest {
    constructor(input: RequestInfo | URL, init?: RequestInit) {
      super(input, init && { ...init, signal: undefined });
    }
  } as typeof Request;
});
afterAll(() => { globalThis.Request = NodeRequest; });

describe("app shell theme toggle", () => {
  it("sits in the top bar", async () => {
    const router = createMemoryRouter([{ path: "/", element: <App /> }], { initialEntries: ["/"] });
    render(
      <QueryClientProvider client={createQueryClient()}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );
    const bar = await screen.findByRole("banner");
    expect(within(bar).getByRole("button", { name: /theme/i })).toBeInTheDocument();
  });
});
