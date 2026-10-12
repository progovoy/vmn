import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { renderWithClient } from "../../test-utils";

vi.mock("../../api", () => ({
  api: { meta: () => Promise.resolve({ version: "1" }), workspaces: () => Promise.resolve([]) },
}));
vi.mock("../../apiModels", () => ({ apiModels: { getModel: vi.fn() } }));
vi.mock("../../apiReports", async (orig) => ({
  ...(await orig<typeof import("../../apiReports")>()),
  apiReports: { getReport: vi.fn() },
}));

vi.mock("../../apiTokens", () => ({ apiTokens: { list: vi.fn() } }));

import { apiModels } from "../../apiModels";
import { apiTokens } from "../../apiTokens";
import { apiReports } from "../../apiReports";
import ModelDetailPage from "../ModelDetail";
import Report from "../Report";
import ReportEdit from "../ReportEdit";
import Tokens from "../Tokens";

const getModel = apiModels.getModel as unknown as ReturnType<typeof vi.fn>;
const listTokens = apiTokens.list as unknown as ReturnType<typeof vi.fn>;
const getReport = apiReports.getReport as unknown as ReturnType<typeof vi.fn>;
const httpError = (status: number, detail: string) =>
  Object.assign(new Error(detail), { status, body: { detail } });

function renderAt(path: string, route: string, element: JSX.Element) {
  return renderWithClient(
    <MemoryRouter initialEntries={[path]}>
      <Routes><Route path={route} element={element} /></Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => vi.clearAllMocks());

describe("ModelDetail not found", () => {
  const renderModel = () =>
    renderAt("/ws/ml-repo/models/resnet", "/ws/:ws/models/:modelName", <ModelDetailPage />);

  it("shows the model not-found on a 404", async () => {
    getModel.mockRejectedValue(httpError(404, "Model resnet not found"));
    renderModel();
    expect(await screen.findByRole("heading", { name: "No model resnet in ml-repo" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "All models" }).getAttribute("href")).toBe("/ws/ml-repo/models");
  });

  it("keeps the error line for any other failure", async () => {
    getModel.mockRejectedValue(httpError(500, "boom"));
    renderModel();
    expect(await screen.findByText(/boom/)).toHaveClass("error");
  });
});

describe("Report not found", () => {
  it("shows the report not-found on a 404", async () => {
    getReport.mockRejectedValue(httpError(404, "Report r_12 not found"));
    renderAt("/ws/ml-repo/reports/r_12", "/ws/:ws/reports/:rid", <Report />);
    expect(await screen.findByRole("heading", { name: "No report r_12 in ml-repo" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "All reports" }).getAttribute("href")).toBe("/ws/ml-repo/reports");
  });

  it("shows the report not-found when editing a missing report", async () => {
    getReport.mockRejectedValue(httpError(404, "Report r_12 not found"));
    renderAt("/ws/ml-repo/reports/r_12/edit", "/ws/:ws/reports/:rid/edit", <ReportEdit />);
    expect(await screen.findByRole("heading", { name: "No report r_12 in ml-repo" })).toBeInTheDocument();
  });

  it("keeps the error line for any other failure", async () => {
    getReport.mockRejectedValue(httpError(500, "boom"));
    renderAt("/ws/ml-repo/reports/r_12", "/ws/:ws/reports/:rid", <Report />);
    expect(await screen.findByText("boom")).toHaveClass("error");
  });
});

describe("Tokens without a control plane", () => {
  it("shows the control-plane page on a 503, without the create form", async () => {
    listTokens.mockRejectedValue(httpError(503, "no control plane"));
    renderAt("/tokens", "/tokens", <Tokens />);
    expect(await screen.findByRole("heading", { name: "API tokens need a control plane" }))
      .toBeInTheDocument();
    expect(screen.queryByLabelText("Token name")).toBeNull();
  });
});
