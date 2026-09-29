import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { renderWithClient } from "../../test-utils";

vi.mock("../../apiModels", () => ({
  apiModels: { getModel: vi.fn(), versionLineage: vi.fn() },
}));

import { apiModels } from "../../apiModels";
import type { ModelDetail, ModelVersion, VersionLineage } from "../../apiModels";
import type { LineageNode } from "../../apiRun";
import ModelDetailPage from "../ModelDetail";

const mocked = apiModels as unknown as {
  getModel: ReturnType<typeof vi.fn>;
  versionLineage: ReturnType<typeof vi.fn>;
};

function version(n: number): ModelVersion {
  return {
    version: n, status: "active", run: { app: "trainer", verstr: `0.${n}.0` },
    artifact_path: "model.pkl", artifact_uri: null, aliases: [], created: null, description: null,
  };
}

const DETAIL: ModelDetail = {
  name: "clf", kind: "model", description: null,
  versions: [version(1), version(2)], aliases: {}, audit: [],
};

function node(app: string, verstr: string, extra: Partial<LineageNode> = {}): LineageNode {
  return {
    app, verstr, name: null, timestamp: null, status: "succeeded",
    depth: 1, found: true, links: [], ...extra,
  };
}

const LINEAGE: VersionLineage = {
  model: "clf", version: 2, kind: "model", status: "active",
  producer: node("trainer", "0.2.0", { name: "train" }),
  consumers: [node("serving", "1.0.0"), node("serving", "0.9.0", { found: false, status: null })],
};

function renderPage() {
  return renderWithClient(
    <MemoryRouter initialEntries={["/ws/myws/models/clf"]}>
      <Routes>
        <Route path="/ws/:ws/models/:modelName" element={<ModelDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mocked.getModel.mockResolvedValue(DETAIL);
  mocked.versionLineage.mockResolvedValue(LINEAGE);
});

describe("ModelDetail lineage panel", () => {
  it("shows the latest version's producer and consumers", async () => {
    renderPage();
    expect(await screen.findByRole("link", { name: "trainer:train" })).toHaveAttribute(
      "href", "/ws/myws/app/trainer/run/0.2.0",
    );
    expect(mocked.versionLineage).toHaveBeenCalledWith("myws", "clf", 2);
    expect(screen.getByText("produced by")).toBeInTheDocument();
    expect(screen.getByText("used by")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "serving:1.0.0" })).toHaveAttribute(
      "href", "/ws/myws/app/serving/run/1.0.0",
    );
    expect(screen.queryByRole("link", { name: "serving:0.9.0" })).toBeNull();
    expect(screen.getByText("missing")).toBeInTheDocument();
  });

  it("refetches for another version", async () => {
    renderPage();
    await screen.findByRole("link", { name: "trainer:train" });
    fireEvent.change(screen.getByLabelText("Lineage version"), { target: { value: "1" } });
    await waitFor(() => expect(mocked.versionLineage).toHaveBeenCalledWith("myws", "clf", 1));
  });

  it("says so when no run used the version", async () => {
    mocked.versionLineage.mockResolvedValue({ ...LINEAGE, producer: null, consumers: [] });
    renderPage();
    expect(await screen.findByText(/no recorded use/i)).toBeInTheDocument();
  });
});
