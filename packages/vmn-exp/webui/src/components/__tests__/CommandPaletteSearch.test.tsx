import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClientProvider, type QueryClient } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";

vi.mock("../../api", () => ({
  api: { recentExperiments: vi.fn(), experimentsPaged: vi.fn(), experiments: vi.fn() },
  appTag: (n: string) => n.replaceAll("/", "-"),
  appName: (t: string) => t.replaceAll("-", "/"),
}));

import { api } from "../../api";
import { createQueryClient } from "../../queryClient";
import CommandPalette from "../CommandPalette";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

function open(client: QueryClient) {
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <CommandPalette ws="w" app="app" workspaces={[]} apps={[]} onClose={() => {}} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  m.recentExperiments.mockResolvedValue([{ verstr: "recent-run", timestamp: null, note: null }]);
});

describe("CommandPalette", () => {
  it("does not refetch the recent runs every time it opens", async () => {
    const client = createQueryClient();
    const first = open(client);
    await screen.findByText("recent-run");
    first.unmount();
    open(client);
    expect(screen.getByText("recent-run")).toBeInTheDocument();
    expect(m.recentExperiments).toHaveBeenCalledTimes(1);
  });

  it("searches every run on the server with RunPicker's clause, debounced", async () => {
    m.experimentsPaged.mockResolvedValue({ rows: [{ verstr: "0.0.9-dev.abc", note: "deep" }], total: 1 });
    open(createQueryClient());
    fireEvent.change(screen.getByPlaceholderText(/jump to/i), { target: { value: "abc" } });
    expect(m.experimentsPaged).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(m.experimentsPaged).toHaveBeenCalledWith(
        "w", "app", expect.objectContaining({ query: 'verstr ~ "abc" or note ~ "abc"', limit: 20 }),
      ),
    );
    expect(await screen.findByText("0.0.9-dev.abc")).toBeInTheDocument();
  });
});
