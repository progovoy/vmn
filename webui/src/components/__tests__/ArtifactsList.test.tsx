import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import ArtifactsList from "../ArtifactsList";

const ARTIFACTS = [
  { name: "model.pt", size: 1048576 },
  { name: "config.json", size: 256 },
  { name: "checkpoint.bin", size: 5242880 },
];

const downloadUrl = (f: string) =>
  `/api/v1/workspaces/main/apps/myapp/experiments/1.0.0-dev.abc.def/artifacts/${f}`;

describe("ArtifactsList", () => {
  it("renders all file names", () => {
    render(<ArtifactsList artifacts={ARTIFACTS} downloadUrl={downloadUrl} />);
    expect(screen.getByText("model.pt")).toBeInTheDocument();
    expect(screen.getByText("config.json")).toBeInTheDocument();
    expect(screen.getByText("checkpoint.bin")).toBeInTheDocument();
  });

  it("shows human-readable file sizes", () => {
    render(<ArtifactsList artifacts={ARTIFACTS} downloadUrl={downloadUrl} />);
    expect(screen.getByText("1.0 MB")).toBeInTheDocument();
    expect(screen.getByText("256 B")).toBeInTheDocument();
    expect(screen.getByText("5.0 MB")).toBeInTheDocument();
  });

  it("renders download links with correct URLs", () => {
    render(<ArtifactsList artifacts={ARTIFACTS} downloadUrl={downloadUrl} />);
    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(3);

    const hrefs = links.map((a) => a.getAttribute("href"));
    expect(hrefs).toContain(
      "/api/v1/workspaces/main/apps/myapp/experiments/1.0.0-dev.abc.def/artifacts/model.pt",
    );
    expect(hrefs).toContain(
      "/api/v1/workspaces/main/apps/myapp/experiments/1.0.0-dev.abc.def/artifacts/config.json",
    );
    expect(hrefs).toContain(
      "/api/v1/workspaces/main/apps/myapp/experiments/1.0.0-dev.abc.def/artifacts/checkpoint.bin",
    );
  });

  it("renders nothing for empty artifacts", () => {
    const { container } = render(
      <ArtifactsList artifacts={[]} downloadUrl={downloadUrl} />,
    );
    expect(container.innerHTML).toBe("");
  });
});
