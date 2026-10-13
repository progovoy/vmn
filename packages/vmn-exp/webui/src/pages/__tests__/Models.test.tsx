import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { renderWithClient } from "../../test-utils";

vi.mock("../../apiModels", () => ({
  apiModels: {
    listModels: vi.fn(),
  },
}));

import { apiModels } from "../../apiModels";
import type { ModelRow } from "../../apiModels";
import Models from "../Models";

const mockedApiModels = apiModels as unknown as {
  listModels: ReturnType<typeof vi.fn>;
};

function renderModels() {
  return renderWithClient(
    <MemoryRouter initialEntries={["/ws/myws/models"]}>
      <Routes>
        <Route path="/ws/:ws/models" element={<Models />} />
      </Routes>
    </MemoryRouter>,
  );
}

const MODELS: ModelRow[] = [
  {
    name: "my-model",
    description: "A test model",
    latest_version: 3,
    aliases: { production: 3, staging: 2 },
    versions_count: 3,
    updated: "2026-01-01T12:00:00Z",
  },
  {
    name: "other-model",
    description: null,
    latest_version: 1,
    aliases: {},
    versions_count: 1,
    updated: "2026-01-02T08:00:00Z",
  },
];

beforeEach(() => {
  vi.clearAllMocks();
});

describe("Models page", () => {
  it("renders model names from API response", async () => {
    mockedApiModels.listModels.mockResolvedValue({ models: MODELS });

    renderModels();

    await waitFor(() => {
      expect(screen.getByText("my-model")).toBeInTheDocument();
    });
    expect(screen.getByText("other-model")).toBeInTheDocument();
  });

  it("shows aliases for models that have them", async () => {
    mockedApiModels.listModels.mockResolvedValue({ models: MODELS });

    renderModels();

    await waitFor(() => {
      expect(screen.getByText("my-model")).toBeInTheDocument();
    });
    expect(screen.getByText(/production/)).toBeInTheDocument();
    expect(screen.getByText(/staging/)).toBeInTheDocument();
  });

  it("links to the model detail page", async () => {
    mockedApiModels.listModels.mockResolvedValue({ models: MODELS });

    renderModels();

    await waitFor(() => {
      expect(screen.getByText("my-model")).toBeInTheDocument();
    });
    const link = screen.getByRole("link", { name: "my-model" });
    expect(link.getAttribute("href")).toContain("my-model");
  });

  it("badges each row with its kind", async () => {
    mockedApiModels.listModels.mockResolvedValue({
      models: [{ ...MODELS[0], kind: "model" }, { ...MODELS[1], name: "train", kind: "dataset" }],
    });

    renderModels();

    expect(await screen.findByText("train")).toBeInTheDocument();
    expect(screen.getByText("dataset")).toHaveClass("badge");
    expect(screen.getByText("model")).toHaveClass("badge");
  });

  it("filters by kind through the API", async () => {
    mockedApiModels.listModels.mockResolvedValue({ models: MODELS });

    renderModels();

    await screen.findByText("my-model");
    expect(mockedApiModels.listModels).toHaveBeenLastCalledWith("myws", undefined);
    fireEvent.click(screen.getByRole("button", { name: "datasets" }));
    await waitFor(() =>
      expect(mockedApiModels.listModels).toHaveBeenLastCalledWith("myws", "dataset"),
    );
  });

  it("picks the kind with the shared segmented control, not a native select", async () => {
    mockedApiModels.listModels.mockResolvedValue({ models: MODELS });

    renderModels();

    await screen.findByText("my-model");
    const group = screen.getByRole("group", { name: "Kind" });
    expect(group).toHaveClass("segmented");
    expect(document.querySelector("select")).toBeNull();
    const pressed = () => within(group).getAllByRole("button")
      .filter((b) => b.getAttribute("aria-pressed") === "true").map((b) => b.textContent);
    expect(pressed()).toEqual(["all kinds"]);
    fireEvent.click(within(group).getByRole("button", { name: "datasets" }));
    await waitFor(() => expect(pressed()).toEqual(["datasets"]));
  });

  it("describes a model without a description instead of a dash", async () => {
    mockedApiModels.listModels.mockResolvedValue({ models: MODELS });

    renderModels();

    await screen.findByText("other-model");
    const row = screen.getByRole("link", { name: "other-model" }).closest("tr")!;
    expect(within(row).queryByText("—")).toBeNull();
    expect(within(row).getByText("latest v1")).toBeInTheDocument();
    const own = screen.getByRole("link", { name: "my-model" }).closest("tr")!;
    expect(within(own).getByText("A test model")).toBeInTheDocument();
  });

  it("drops the redundant subtitle", async () => {
    mockedApiModels.listModels.mockResolvedValue({ models: MODELS });

    renderModels();

    await screen.findByText("my-model");
    expect(screen.getByRole("heading", { level: 1, name: "Models" })).toBeInTheDocument();
    expect(document.querySelector(".page-head .what")).toBeNull();
  });

  it("shows empty state when there are no models", async () => {
    mockedApiModels.listModels.mockResolvedValue({ models: [] });

    renderModels();

    await waitFor(() => {
      expect(screen.getByText(/no models/i)).toBeInTheDocument();
    });
  });
});
