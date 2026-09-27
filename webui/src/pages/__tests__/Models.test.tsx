import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
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

  it("shows empty state when there are no models", async () => {
    mockedApiModels.listModels.mockResolvedValue({ models: [] });

    renderModels();

    await waitFor(() => {
      expect(screen.getByText(/no models/i)).toBeInTheDocument();
    });
  });
});
