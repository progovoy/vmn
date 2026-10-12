import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { fireEvent } from "@testing-library/react";
import { Link, MemoryRouter, Route, Routes } from "react-router-dom";

vi.mock("../../api", () => ({
  api: { apps: vi.fn(), versions: vi.fn(), action: vi.fn(), job: vi.fn() },
  appTag: (n: string) => n.replaceAll("/", "-"),
  appName: (t: string) => t.replaceAll("-", "/"),
}));

import { api } from "../../api";
import Actions from "../Actions";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

function renderAt(url: string) {
  render(
    <MemoryRouter initialEntries={[url]}>
      <Routes><Route path="/ws/:ws/app/:app/actions" element={<Actions />} /></Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  m.apps.mockResolvedValue([{ name: "ml_app", experiments: 1, versions: 2 }]);
  m.versions.mockResolvedValue([{ verstr: "1.2.0", kind: "version" }]);
});

describe("Actions ?goto= prefill", () => {
  it("fills the goto version from the URL and its CLI hint, without running it", async () => {
    renderAt("/ws/w/app/ml_app/actions?goto=1.2.0");
    expect(screen.getByDisplayValue("1.2.0")).toBeInTheDocument();
    expect(screen.getByText(/vmn goto -v 1\.2\.0 ml_app/)).toBeInTheDocument();
    await waitFor(() => expect(m.versions).toHaveBeenCalled());
    expect(m.action).not.toHaveBeenCalled();
  });

  it("refills when ?goto= changes while the page stays mounted (⌘K on Actions)", async () => {
    render(
      <MemoryRouter initialEntries={["/ws/w/app/ml_app/actions"]}>
        <Link to="/ws/w/app/ml_app/actions?goto=1.3.0">palette</Link>
        <Routes><Route path="/ws/:ws/app/:app/actions" element={<Actions />} /></Routes>
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByText("palette"));
    expect(await screen.findByDisplayValue("1.3.0")).toBeInTheDocument();
    expect(m.action).not.toHaveBeenCalled();
  });

  it("leaves the version empty without the param", () => {
    renderAt("/ws/w/app/ml_app/actions");
    expect(screen.queryByDisplayValue("1.2.0")).toBeNull();
    expect(m.action).not.toHaveBeenCalled();
  });
});
