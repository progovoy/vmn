import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClientProvider, type QueryClient } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";

vi.mock("../../api", () => ({
  api: { recentExperiments: vi.fn(), experimentsPaged: vi.fn(), experiments: vi.fn() },
  appTag: (n: string) => n.replaceAll("/", "-"),
  appName: (t: string) => t.replaceAll("-", "/"),
}));
vi.mock("../../apiRunSearch", () => ({ searchRuns: vi.fn() }));

import { api } from "../../api";
import * as runSearch from "../../apiRunSearch";
import { createQueryClient } from "../../queryClient";
import CommandPalette from "../CommandPalette";
import { fakeCtx } from "../palette/__tests__/fakeCtx";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const s = runSearch as unknown as Record<string, ReturnType<typeof vi.fn>>;

function open(client: QueryClient) {
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <CommandPalette ctx={fakeCtx({ ws: "w", app: "app", workspaces: [] })} onClose={() => {}} />
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

  it("goes to any run through the server's run search, debounced (plan 23 W11)", async () => {
    s.searchRuns.mockResolvedValue([{
      verstr: "0.0.9-dev.abc", idx: 1903, name: "lr_layers_grid-t1903", status: "succeeded",
      root: "0.0.1-dev.j", root_name: "lr_layers_grid", match: "name",
    }]);
    open(createQueryClient());
    fireEvent.change(screen.getByPlaceholderText(/jump to/i), { target: { value: "t1903" } });
    expect(s.searchRuns).not.toHaveBeenCalled();
    await waitFor(() => expect(s.searchRuns).toHaveBeenCalledWith("w", "app", "t1903", 20));
    expect(m.experimentsPaged).not.toHaveBeenCalled();
    const item = (await screen.findByText("lr_layers_grid-t1903")).closest("[role=option]")!;
    expect(item.textContent).toContain("@1,903");
    expect(item.textContent).toContain("in lr_layers_grid");
  });

  it("a top-level hit is not said to be in a job", async () => {
    s.searchRuns.mockResolvedValue([{
      verstr: "0.0.9-dev.top", idx: 7, name: "solo", status: "running", root: null, root_name: null, match: "name",
    }]);
    open(createQueryClient());
    fireEvent.change(screen.getByPlaceholderText(/jump to/i), { target: { value: "solo" } });
    const item = (await screen.findByText("solo")).closest("[role=option]")!;
    expect(item.textContent).not.toContain(" in ");
  });

  it("offers no Snapshots page", async () => {
    open(createQueryClient());
    await screen.findByText("recent-run");
    expect(screen.getByText("Stamp tree")).toBeInTheDocument();
    expect(screen.queryByText("Snapshots")).toBeNull();
  });
});
