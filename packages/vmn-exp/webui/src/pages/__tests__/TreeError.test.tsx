import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClientProvider } from "@tanstack/react-query";
import { createQueryClient } from "../../queryClient";

vi.mock("../../api", () => ({
  api: { versions: vi.fn() },
  appName: (t: string) => t.replaceAll("-", "/"),
}));

import { api } from "../../api";
import StampTree from "../StampTree";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

function renderTree() {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <MemoryRouter initialEntries={["/ws/w/app/my-app/tree"]}>
        <Routes>
          <Route path="/ws/:ws/app/:app/tree" element={<StampTree />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => vi.clearAllMocks());

describe("StampTree 409 error", () => {
  it("renders a cause and a git status hint when the API returns 409 not_a_repo", async () => {
    const err = Object.assign(
      new Error("Not a git repository"),
      { status: 409, body: { detail: "Not a git repository", reason: "not_a_repo", path: "/some/path" } },
    );
    m.versions.mockRejectedValue(err);
    renderTree();
    // The hint must mention the path and suggest `git status` (not just show the raw error)
    await waitFor(() => {
      expect(screen.getByText(/not a git repository/i)).toBeInTheDocument();
    });
    expect(screen.getAllByText(/\/some\/path/).length).toBeGreaterThan(0);
    // The cli-card with the git status command
    const cliCard = document.querySelector(".cli-card");
    expect(cliCard).not.toBeNull();
    expect(cliCard!.textContent).toMatch(/git -C.*status/);
  });

  it("still shows a generic error for non-409 failures", async () => {
    m.versions.mockRejectedValue(new Error("Server error"));
    renderTree();
    await waitFor(() => {
      expect(screen.getByText(/server error/i)).toBeInTheDocument();
    });
  });
});
