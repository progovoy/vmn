import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { renderWithClient } from "../../test-utils";

vi.mock("../../api", () => ({
  api: {
    meta: vi.fn(),
    experiment: vi.fn(),
    metricsSchema: vi.fn(),
  },
  appName: (tag: string) => tag.replaceAll("-", "/"),
  artifactUrl: (_ws: string, _app: string, _verstr: string, name: string) =>
    `/api/v1/artifacts/${name}`,
}));

vi.mock("../../apiModels", () => ({
  apiModels: {
    registerVersion: vi.fn(),
  },
}));

import { api } from "../../api";
import { apiModels } from "../../apiModels";
import type { ExperimentDetail } from "../../types";
import Run from "../Run";

const mockedApi = api as unknown as {
  meta: ReturnType<typeof vi.fn>;
  experiment: ReturnType<typeof vi.fn>;
  metricsSchema: ReturnType<typeof vi.fn>;
};

const mockedApiModels = apiModels as unknown as {
  registerVersion: ReturnType<typeof vi.fn>;
};

function makeDetail(): ExperimentDetail {
  return {
    metadata: {
      verstr: "0.1.0",
      branch: "main",
      base_version: "0.1.0",
      base_commit: "abc1234",
      timestamp: "2026-01-01T12:00:00Z",
    },
    metrics: {},
    series: {},
    patches: {},
    artifacts: [{ name: "model.pkl", size: 1024 }],
  };
}

function renderRun() {
  return renderWithClient(
    <MemoryRouter initialEntries={["/ws/myws/app/my-app/run/0.1.0"]}>
      <Routes>
        <Route path="/ws/:ws/app/:app/run/:verstr" element={<Run />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mockedApi.metricsSchema.mockResolvedValue({});
});

describe("Register as model button", () => {
  it("shows the register button when artifacts are present", async () => {
    mockedApi.meta.mockResolvedValue({ version: "1.0.0" });
    mockedApi.experiment.mockResolvedValue(makeDetail());

    renderRun();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /register as model/i })).toBeInTheDocument();
    });
  });

  it("opens a dialog when the register button is clicked", async () => {
    mockedApi.meta.mockResolvedValue({ version: "1.0.0" });
    mockedApi.experiment.mockResolvedValue(makeDetail());

    renderRun();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /register as model/i })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /register as model/i }));

    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("posts to register a version when the dialog is submitted", async () => {
    mockedApi.meta.mockResolvedValue({ version: "1.0.0" });
    mockedApi.experiment.mockResolvedValue(makeDetail());
    mockedApiModels.registerVersion.mockResolvedValue({});

    renderRun();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /register as model/i })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /register as model/i }));

    const nameInput = screen.getByRole("textbox", { name: /model name/i });
    fireEvent.change(nameInput, { target: { value: "my-model" } });

    fireEvent.click(screen.getByRole("button", { name: /^register$/i }));

    await waitFor(() => {
      expect(mockedApiModels.registerVersion).toHaveBeenCalledWith(
        "myws", "my-model",
        { run: { app: "my/app", verstr: "0.1.0" }, artifact_path: undefined, alias: undefined, description: undefined },
      );
    });
  });

  it("is hidden when the server reports read-only mode", async () => {
    mockedApi.meta.mockResolvedValue({ version: "1.0.0", read_only: true });
    mockedApi.experiment.mockResolvedValue(makeDetail());

    renderRun();

    await waitFor(() => {
      // artifacts card should be rendered
      expect(screen.getByText("model.pkl")).toBeInTheDocument();
    });

    expect(screen.queryByRole("button", { name: /register as model/i })).not.toBeInTheDocument();
  });
});
