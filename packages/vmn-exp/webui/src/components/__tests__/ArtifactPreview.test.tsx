import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import ArtifactsList from "../ArtifactsList";
import { TEXT_PREVIEW_BYTES } from "../../util/artifactKinds";

const url = (f: string) => `/api/v1/x/artifacts/${f}`;
const textResponse = (body: string, status = 200) =>
  Promise.resolve(new Response(body, { status }));

let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  fetchMock = vi.fn(() => textResponse("hello"));
  vi.stubGlobal("fetch", fetchMock);
  sessionStorage.clear();
});
afterEach(() => { vi.unstubAllGlobals(); sessionStorage.clear(); });

const previewOf = (name: string) =>
  within(screen.getByText(name).closest("li")!).getByRole("button", { name: /preview/i });

describe("artifact tree", () => {
  const nested = [
    { name: "plots/loss.png", size: 10 },
    { name: "plots/deep/acc.png", size: 10 },
    { name: "model.pt", size: 10 },
  ];

  it("shows nested names under collapsible folders", () => {
    render(<ArtifactsList artifacts={nested} downloadUrl={url} />);
    const folder = screen.getByRole("button", { name: /plots/ });
    expect(folder).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("loss.png")).toBeInTheDocument();
    fireEvent.click(folder);
    expect(folder).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("loss.png")).toBeNull();
    expect(screen.getByText("model.pt")).toBeInTheDocument();
  });

  it("links nested files to their full path", () => {
    render(<ArtifactsList artifacts={nested} downloadUrl={url} />);
    expect(screen.getByText("acc.png").closest("a")).toHaveAttribute("href", url("plots/deep/acc.png"));
  });

  it("offers no preview for binary files", () => {
    render(<ArtifactsList artifacts={nested} downloadUrl={url} />);
    const li = screen.getByText("model.pt").closest("li")!;
    expect(within(li).queryByRole("button", { name: /preview/i })).toBeNull();
  });
});

describe("artifact preview", () => {
  it("never fetches until a preview is asked for", () => {
    render(<ArtifactsList artifacts={[{ name: "a.txt", size: 5 }]} downloadUrl={url} />);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("shows an image inline from its download URL", () => {
    render(<ArtifactsList artifacts={[{ name: "p/plot.png", size: 5 }]} downloadUrl={url} />);
    fireEvent.click(previewOf("plot.png"));
    expect(screen.getByRole("img", { name: "p/plot.png" })).toHaveAttribute("src", url("p/plot.png"));
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("fetches an image with the token into a blob URL when one is set", async () => {
    sessionStorage.setItem("vmn_token", "t0k");
    const create = vi.fn(() => "blob:img");
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: create, revokeObjectURL: vi.fn() }));
    render(<ArtifactsList artifacts={[{ name: "plot.png", size: 5 }]} downloadUrl={url} />);
    fireEvent.click(previewOf("plot.png"));
    await waitFor(() => expect(screen.getByRole("img", { name: "plot.png" })).toHaveAttribute("src", "blob:img"));
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer t0k");
  });

  it("renders a csv's first 100 rows as a table, fetching only a byte range", async () => {
    const csv = ["step,loss", ...Array.from({ length: 150 }, (_, i) => `${i},0.${i}`)].join("\n");
    fetchMock.mockImplementation(() => textResponse(csv));
    render(<ArtifactsList artifacts={[{ name: "m.csv", size: csv.length }]} downloadUrl={url} />);
    fireEvent.click(previewOf("m.csv"));
    const table = await screen.findByRole("table");
    expect(within(table).getByText("loss").tagName).toBe("TH");
    expect(within(table).getAllByRole("row")).toHaveLength(101);
    expect(screen.getByText(/first 100 rows/)).toBeInTheDocument();
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect((init.headers as Record<string, string>).Range).toBe(`bytes=0-${TEXT_PREVIEW_BYTES - 1}`);
  });

  it("parses a tsv on tabs", async () => {
    fetchMock.mockImplementation(() => textResponse("a\tb\n1\t2"));
    render(<ArtifactsList artifacts={[{ name: "m.tsv", size: 8 }]} downloadUrl={url} />);
    fireEvent.click(previewOf("m.tsv"));
    const table = await screen.findByRole("table");
    expect(within(table).getByText("2")).toBeInTheDocument();
  });

  it("shows text in a pre and notes when it was truncated", async () => {
    fetchMock.mockImplementation(() => textResponse("x".repeat(TEXT_PREVIEW_BYTES + 50)));
    render(<ArtifactsList artifacts={[{ name: "train.log", size: TEXT_PREVIEW_BYTES * 3 }]} downloadUrl={url} />);
    fireEvent.click(previewOf("train.log"));
    await waitFor(() => expect(document.querySelector("pre.artifact-text")).not.toBeNull());
    expect(document.querySelector("pre.artifact-text")!.textContent!.length).toBe(TEXT_PREVIEW_BYTES);
    expect(screen.getByText(/truncated/i)).toBeInTheDocument();
  });

  it("does not claim truncation for a small file", async () => {
    render(<ArtifactsList artifacts={[{ name: "c.json", size: 5 }]} downloadUrl={url} />);
    fireEvent.click(previewOf("c.json"));
    expect(await screen.findByText("hello")).toBeInTheDocument();
    expect(screen.queryByText(/truncated/i)).toBeNull();
  });

  it("reports a failed fetch", async () => {
    fetchMock.mockImplementation(() => textResponse("nope", 404));
    render(<ArtifactsList artifacts={[{ name: "c.json", size: 5 }]} downloadUrl={url} />);
    fireEvent.click(previewOf("c.json"));
    expect(await screen.findByText(/HTTP 404/)).toBeInTheDocument();
  });

  it("closes again from the same button", async () => {
    render(<ArtifactsList artifacts={[{ name: "c.json", size: 5 }]} downloadUrl={url} />);
    fireEvent.click(previewOf("c.json"));
    await screen.findByText("hello");
    const btn = previewOf("c.json");
    expect(btn).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(btn);
    expect(screen.queryByText("hello")).toBeNull();
  });
});
