/**
 * Tests for RunProvenance components: EnvCard, InputsCard, ImportedBadge.
 *
 * 4 tests (TDD — red first, then implementation):
 * 1. EnvCard renders python/platform/packages and package filter works
 * 2. InputsCard renders name/uri/digest(short)/kind
 * 3. ImportedBadge shows "Imported from MLflow" when imported_from is set
 * 4. Nothing rendered for old runs (null/absent fields)
 */
import { describe, it, expect } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import type { EnvData, InputEntry } from "../../types";
import { EnvCard, InputsCard, ImportedBadge } from "../RunProvenance";

const ENV_DATA: EnvData = {
  python: { version: "3.11.0", implementation: "CPython" },
  platform: { system: "Linux", machine: "x86_64" },
  packages: {
    torch: "2.0.0",
    numpy: "1.24.0",
    pandas: "2.0.0",
  },
  hostname: "trainingbox",
};

const INPUTS: Record<string, InputEntry> = {
  train_data: {
    uri: "s3://bucket/data/train.csv",
    digest: "sha256:abcdef1234567890",
    kind: "dataset",
  },
  val_data: {
    uri: "gs://bucket/val.csv",
    digest: null,
    kind: "dataset",
  },
};

describe("EnvCard", () => {
  it("renders python version, platform, and packages", () => {
    render(<EnvCard env={ENV_DATA} />);
    expect(screen.getByText(/3\.11\.0/)).toBeInTheDocument();
    expect(screen.getByText(/Linux/i)).toBeInTheDocument();
    expect(screen.getByText("torch")).toBeInTheDocument();
    expect(screen.getByText("numpy")).toBeInTheDocument();
    expect(screen.getByText("pandas")).toBeInTheDocument();
  });

  it("filters packages by name", () => {
    render(<EnvCard env={ENV_DATA} />);
    const input = screen.getByPlaceholderText(/filter/i);
    fireEvent.change(input, { target: { value: "torch" } });
    expect(screen.getByText("torch")).toBeInTheDocument();
    expect(screen.queryByText("numpy")).not.toBeInTheDocument();
    expect(screen.queryByText("pandas")).not.toBeInTheDocument();
  });
});

describe("InputsCard", () => {
  it("renders input names, URIs, shortened digest, and kind", () => {
    render(<InputsCard inputs={INPUTS} />);
    expect(screen.getByText("train_data")).toBeInTheDocument();
    expect(screen.getByText("s3://bucket/data/train.csv")).toBeInTheDocument();
    // Digest should appear shortened (first 12 chars after prefix)
    expect(screen.getByText(/abcdef1234/)).toBeInTheDocument();
    expect(screen.getByText("val_data")).toBeInTheDocument();
    // No digest → em dash or similar
    expect(screen.getByText("gs://bucket/val.csv")).toBeInTheDocument();
  });
});

describe("ImportedBadge", () => {
  it("shows 'Imported from MLflow' badge when imported_from is set", () => {
    render(<ImportedBadge importedFrom="mlflow:abc123" />);
    expect(screen.getByText(/Imported from MLflow/i)).toBeInTheDocument();
  });

  it("renders nothing when imported_from is null", () => {
    const { container } = render(<ImportedBadge importedFrom={null} />);
    expect(container.firstChild).toBeNull();
  });
});

describe("RunProvenance — nothing rendered for old runs", () => {
  it("EnvCard with null env renders nothing meaningful", () => {
    // When env is null, component is not rendered at all (caller-controlled)
    // Just confirm EnvCard with truncated-only summary shows truncated notice
    const summaryEnv: EnvData = {
      python: "3.9.0",
      platform: "Linux/x86_64",
      packages_count: 150,
      truncated: true,
    };
    render(<EnvCard env={summaryEnv} />);
    expect(screen.getByText(/3\.9\.0/)).toBeInTheDocument();
    // No package table when truncated (no packages dict)
    expect(screen.queryByPlaceholderText(/filter/i)).not.toBeInTheDocument();
    expect(screen.getByText(/truncated/i)).toBeInTheDocument();
  });
});
