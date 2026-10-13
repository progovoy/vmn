import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import DiffText from "../DiffText";

describe("DiffText", () => {
  it("classes each line by its unified-diff role", () => {
    render(<DiffText text={"diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -1 +1 @@\n-old\n+new\n ctx"} />);
    expect(screen.getByText("diff --git a/x b/x")).toHaveClass("file");
    expect(screen.getByText("@@ -1 +1 @@")).toHaveClass("hunk");
    expect(screen.getByText("-old")).toHaveClass("del");
    expect(screen.getByText("+new")).toHaveClass("add");
    expect(screen.getByText("--- a/x").className).toBe("");
    expect(screen.getByText("+++ b/x").className).toBe("");
  });

  it("keeps blank lines as rows", () => {
    const { container } = render(<DiffText text={"+a\n\n+b"} />);
    expect(container.querySelectorAll(".diff pre > div")).toHaveLength(3);
  });
});
