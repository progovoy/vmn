import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import RunOutput from "../RunOutput";

const url = (f: string) => `/api/v1/x/artifacts/${f}`;
let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  fetchMock = vi.fn(() => Promise.resolve(new Response("epoch 1 loss=0.3\nTraceback: boom")));
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

describe("RunOutput", () => {
  it("shows the run's output.log inline", async () => {
    render(<RunOutput artifacts={[{ name: "model.pt", size: 9 }, { name: "output.log", size: 30 }]} downloadUrl={url} />);
    expect(screen.getByText("output")).toBeInTheDocument();
    expect(await screen.findByText(/Traceback: boom/)).toBeInTheDocument();
    expect(fetchMock.mock.calls[0][0]).toBe(url("output.log"));
  });

  it("renders nothing for a run without output.log", () => {
    const { container } = render(<RunOutput artifacts={[{ name: "model.pt", size: 9 }]} downloadUrl={url} />);
    expect(container.innerHTML).toBe("");
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
