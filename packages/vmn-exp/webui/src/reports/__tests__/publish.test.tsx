import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { ReactNode } from "react";
import { renderWithClient } from "../../test-utils";

vi.mock("../../components/LazyMount", () => ({ default: ({ children }: { children: ReactNode }) => <>{children}</> }));
vi.mock("../../api", () => ({
  api: { experiment: vi.fn(), experimentsPaged: vi.fn() },
  appTag: (a: string) => a.replaceAll("/", "-"),
  artifactUrl: () => "/x",
}));
vi.mock("../../apiReports", async (orig) => ({
  ...(await orig<typeof import("../../apiReports")>()),
  apiReports: { getPanelData: vi.fn() },
}));

import { api } from "../../api";
import { apiReports } from "../../apiReports";
import Panel from "../Panel";
import { PanelCaptureProvider, usePanelCapture, type PanelCapture } from "../publishedData";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const mr = apiReports as unknown as Record<string, ReturnType<typeof vi.fn>>;

const DETAIL = {
  metadata: { verstr: "a" }, metrics: { loss: 0.5 }, params: { lr: 0.1 }, series: {}, patches: {},
  status: { status: "succeeded", exit_code: 0 },
  media: { img: [{ step: 1, path: "media/img/1.png" }] },
};
const SPEC = { v: 1, id: "card", app: "my_app", type: "run", runs: { verstrs: ["a"] } };
const MEDIA = { ...SPEC, id: "pic", type: "media", key: "img" };

type Payload = { app: string; verstrs: string[]; media: string[]; queries: unknown[] };

let capture: PanelCapture | null = null;
function Grab() {
  capture = usePanelCapture();
  return null;
}
const wrap = (ui: ReactNode) => renderWithClient(<MemoryRouter>{ui}</MemoryRouter>);

beforeEach(() => {
  vi.clearAllMocks();
  capture = null;
});

describe("report publish", () => {
  it("captures each live panel's fetched payload with its runs and media refs", async () => {
    m.experiment.mockResolvedValue(DETAIL);
    wrap(<PanelCaptureProvider><Grab /><Panel ws="w" spec={SPEC} /><Panel ws="w" spec={MEDIA} /></PanelCaptureProvider>);
    await screen.findByText("a");
    await waitFor(() => expect(Object.keys(capture!.collect()).sort()).toEqual(["card", "pic"]));
    const data = capture!.collect() as Record<string, Payload>;
    expect(data.card.app).toBe("my_app");
    expect(data.card.verstrs).toEqual(["a"]);
    expect(data.card.queries).toHaveLength(1);
    expect(data.pic.media).toEqual(["vmn://my_app/a/media/img/1.png"]);
  });

  it("renders a published panel from its data and never queries the runs API", async () => {
    m.experiment.mockResolvedValue(DETAIL);
    const first = wrap(<PanelCaptureProvider><Grab /><Panel ws="w" spec={SPEC} /></PanelCaptureProvider>);
    await screen.findByText("a");
    await waitFor(() => expect(capture!.collect().card).toBeTruthy());
    const payload = JSON.parse(JSON.stringify(capture!.collect().card));
    first.unmount();
    vi.clearAllMocks();
    m.experiment.mockRejectedValue(new Error("must not query"));
    mr.getPanelData.mockResolvedValue(payload);
    wrap(<Panel ws="w" spec={SPEC} published={{ rid: "r1", rev: 3 }} />);
    expect(await screen.findByText("a")).toBeTruthy();
    expect(screen.getByText("lr")).toBeTruthy();
    expect(mr.getPanelData).toHaveBeenCalledWith("w", "r1", 3, "card");
    expect(m.experiment).not.toHaveBeenCalled();
  });

  it("shows a 'run pruned' placeholder for a missing run in a live panel", async () => {
    m.experiment.mockRejectedValue(Object.assign(new Error("Not found"), { status: 404 }));
    wrap(<Panel ws="w" spec={SPEC} />);
    expect(await screen.findByText(/run pruned/)).toBeTruthy();
  });
});
