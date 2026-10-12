import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { renderWithClient } from "../../test-utils";

vi.mock("../../apiTokens", () => ({
  apiTokens: { list: vi.fn(), create: vi.fn(), revoke: vi.fn() },
}));
const meta = vi.fn();
vi.mock("../../api", () => ({
  api: { meta: () => meta(), workspaces: () => Promise.resolve([]) },
  appName: (tag: string) => tag.replaceAll("-", "/"),
}));

import { apiTokens, type TokenRecord } from "../../apiTokens";
import Tokens from "../Tokens";

const api = apiTokens as unknown as Record<"list" | "create" | "revoke", ReturnType<typeof vi.fn>>;

const CI: TokenRecord = {
  id: "abc", name: "ci", roles: { ml: "viewer" }, owner: "oidc:u1",
  created_at: 1_700_000_000, expires_at: 0, revoked: false,
};

function renderTokens() {
  return renderWithClient(<MemoryRouter><Tokens /></MemoryRouter>);
}

beforeEach(() => {
  vi.clearAllMocks();
  meta.mockResolvedValue({ version: "1", control_plane: true });
});

describe("Tokens page", () => {
  it("lists tokens with their roles and state", async () => {
    api.list.mockResolvedValue([CI, { ...CI, id: "old", name: "old", revoked: true }]);
    renderTokens();
    expect(await screen.findByText("ci")).toBeInTheDocument();
    expect(screen.getAllByText("ml: viewer")).toHaveLength(2);
    expect(screen.getByText("revoked")).toBeInTheDocument();
  });

  it("creates a token and shows the secret once", async () => {
    api.list.mockResolvedValue([]);
    api.create.mockResolvedValue({ token: "vmnx_abc_s3cret", record: CI });
    renderTokens();
    fireEvent.change(await screen.findByLabelText("Token name"), { target: { value: "ci" } });
    fireEvent.change(screen.getByLabelText("Workspace"), { target: { value: "ml" } });
    fireEvent.change(screen.getByLabelText("Role"), { target: { value: "editor" } });
    fireEvent.click(screen.getByRole("button", { name: "Create token" }));
    await waitFor(() =>
      expect(api.create).toHaveBeenCalledWith({ name: "ci", roles: { ml: "editor" } }));
    expect(await screen.findByText("vmnx_abc_s3cret")).toBeInTheDocument();
  });

  it("revokes a token", async () => {
    api.list.mockResolvedValue([CI]);
    api.revoke.mockResolvedValue(undefined);
    renderTokens();
    fireEvent.click(await screen.findByRole("button", { name: "Revoke ci" }));
    await waitFor(() => expect(api.revoke).toHaveBeenCalledWith("abc"));
  });

  it("explains a server without a control plane, from meta, without asking for tokens", async () => {
    meta.mockResolvedValue({ version: "1", control_plane: false });
    renderTokens();
    expect(await screen.findByRole("heading", { name: "API tokens need a control plane" })).toBeInTheDocument();
    expect(api.list).not.toHaveBeenCalled();
  });

  it("shows any failure of the list as an error, a 503 included", async () => {
    api.list.mockRejectedValue(Object.assign(new Error("store unavailable"), { status: 503 }));
    renderTokens();
    expect(await screen.findByText(/store unavailable/)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "API tokens need a control plane" })).toBeNull();
  });
});
