/** Plan 28 N7: the facet sidebar lists the scoped facets' top note
 *  signatures; a click adds a `notes ~` clause for one. */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, within } from "@testing-library/react";
import { renderWithClient } from "../../test-utils";

vi.mock("../../api", async (orig) => {
  const actual = await orig<typeof import("../../api")>();
  return { ...actual, api: { facets: vi.fn(), experimentGroups: vi.fn(), experimentsColumns: vi.fn() } };
});

import { api } from "../../api";
import FacetSidebar from "../FacetSidebar";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const FACETS = {
  branches: [], metric_keys: [], param_keys: [], tag_keys: [], param_values: {}, parented: 0, total: 40,
};

beforeEach(() => {
  vi.clearAllMocks();
  m.experimentGroups.mockResolvedValue({ groups: [], total_groups: 0, total_rows: 0, aggregate: "mean", running: 0 });
});

describe("FacetSidebar notes", () => {
  it("lists the note signatures by runs and adds a notes clause for one", async () => {
    m.facets.mockResolvedValue({
      ...FACETS,
      note_sigs: [
        { sig: "Received SIGTERM at step <n>", runs: 30, count: 41 },
        { sig: 'retry "<n>"', runs: 2, count: 2 },
      ],
    });
    const onAdd = vi.fn();
    renderWithClient(<FacetSidebar ws="w" app="a" scope="J" query="" status="" onAdd={onAdd} />);
    const list = await screen.findByRole("list", { name: "notes values" });
    const buttons = within(list).getAllByRole("button");
    expect(buttons[0]).toHaveAccessibleName('notes ~ "Received SIGTERM at step <n>" (30 runs)');
    fireEvent.click(buttons[0]);
    expect(onAdd).toHaveBeenCalledWith(['notes ~ "Received SIGTERM at step <n>"']);
    expect(buttons[1]).toHaveAccessibleName("notes ~ 'retry \"<n>\"' (2 runs)");
  });

  it("has no notes section when the runs logged none", async () => {
    m.facets.mockResolvedValue(FACETS);
    renderWithClient(<FacetSidebar ws="w" app="a" scope="J" query="" status="" onAdd={() => {}} />);
    await screen.findByRole("region", { name: "status" });
    expect(screen.queryByRole("region", { name: "notes" })).toBeNull();
  });
});
