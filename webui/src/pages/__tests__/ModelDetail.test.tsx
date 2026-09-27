import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { renderWithClient } from "../../test-utils";

vi.mock("../../apiModels", () => ({
  apiModels: {
    getModel: vi.fn(),
    moveAlias: vi.fn(),
  },
}));

import { apiModels } from "../../apiModels";
import type { ModelDetail } from "../../apiModels";
import ModelDetailPage from "../ModelDetail";

const mockedApiModels = apiModels as unknown as {
  getModel: ReturnType<typeof vi.fn>;
  moveAlias: ReturnType<typeof vi.fn>;
};

function renderModelDetail(model = "my-model") {
  return renderWithClient(
    <MemoryRouter initialEntries={[`/ws/myws/models/${model}`]}>
      <Routes>
        <Route path="/ws/:ws/models/:modelName" element={<ModelDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

const MODEL_DETAIL: ModelDetail = {
  name: "my-model",
  description: "A model for testing",
  versions: [
    {
      version: 1,
      status: "deprecated",
      run: { app: "my-app", verstr: "0.1.0" },
      artifact_path: "model.pkl",
      artifact_uri: null,
      aliases: [],
      created: "2026-01-01T10:00:00Z",
      description: null,
    },
    {
      version: 2,
      status: "active",
      run: { app: "my-app", verstr: "0.2.0" },
      artifact_path: "model.pkl",
      artifact_uri: null,
      aliases: ["staging"],
      created: "2026-01-02T10:00:00Z",
      description: "Better model",
    },
    {
      version: 3,
      status: "active",
      run: { app: "my-app", verstr: "0.3.0" },
      artifact_path: "model.pkl",
      artifact_uri: null,
      aliases: ["production"],
      created: "2026-01-03T10:00:00Z",
      description: null,
    },
  ],
  aliases: { production: 3, staging: 2 },
  audit: [
    { ts: "2026-01-01T11:00:00Z", actor: "alice@example.com", type: "register", alias: null, version: 1, status: null },
    { ts: "2026-01-03T12:00:00Z", actor: "bob@example.com", type: "alias", alias: "production", version: 3, status: null },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("ModelDetail page", () => {
  it("renders version numbers and status", async () => {
    mockedApiModels.getModel.mockResolvedValue(MODEL_DETAIL);

    renderModelDetail();

    await waitFor(() => {
      expect(screen.getByText("v1")).toBeInTheDocument();
    });
    expect(screen.getByText("v2")).toBeInTheDocument();
    expect(screen.getByText("v3")).toBeInTheDocument();
    expect(screen.getByText("deprecated")).toBeInTheDocument();
  });

  it("links to the run page for each version", async () => {
    mockedApiModels.getModel.mockResolvedValue(MODEL_DETAIL);

    renderModelDetail();

    await waitFor(() => {
      expect(screen.getByText("0.1.0")).toBeInTheDocument();
    });
    const link = screen.getByRole("link", { name: "0.1.0" });
    expect(link.getAttribute("href")).toContain("my-app");
    expect(link.getAttribute("href")).toContain("0.1.0");
  });

  it("shows aliases on versions", async () => {
    mockedApiModels.getModel.mockResolvedValue(MODEL_DETAIL);

    renderModelDetail();

    await waitFor(() => {
      expect(screen.getByText("staging")).toBeInTheDocument();
    });
    expect(screen.getByText("production")).toBeInTheDocument();
  });

  it("moves alias by calling POST with expect when confirmed", async () => {
    mockedApiModels.getModel.mockResolvedValue(MODEL_DETAIL);
    mockedApiModels.moveAlias.mockResolvedValue({});

    renderModelDetail();

    await waitFor(() => {
      expect(screen.getByText("v3")).toBeInTheDocument();
    });

    // Open the alias move control for 'staging' (currently on v2)
    const moveBtn = screen.getByRole("button", { name: /move staging/i });
    fireEvent.click(moveBtn);

    // A dialog or input should appear — set a new version number
    const input = screen.getByRole("spinbutton", { name: /version/i });
    fireEvent.change(input, { target: { value: "3" } });

    const confirmBtn = screen.getByRole("button", { name: /confirm/i });
    fireEvent.click(confirmBtn);

    await waitFor(() => {
      expect(mockedApiModels.moveAlias).toHaveBeenCalledWith(
        "myws", "my-model", "staging", 3, 2,
      );
    });
  });

  it("shows the audit log", async () => {
    mockedApiModels.getModel.mockResolvedValue(MODEL_DETAIL);

    renderModelDetail();

    await waitFor(() => {
      expect(screen.getByText(/alice@example.com/)).toBeInTheDocument();
    });
    expect(screen.getByText(/bob@example.com/)).toBeInTheDocument();
    expect(screen.getByText(/register/)).toBeInTheDocument();
  });
});
