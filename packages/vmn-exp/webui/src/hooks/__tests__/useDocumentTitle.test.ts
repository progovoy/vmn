import { describe, it, expect } from "vitest";
import { renderHook } from "@testing-library/react";
import { useDocumentTitle } from "../useDocumentTitle";

describe("useDocumentTitle", () => {
  it("sets document.title and follows changes", () => {
    const { rerender } = renderHook(({ title }) => useDocumentTitle(title), {
      initialProps: { title: "workspaces — vmn-exp" },
    });
    expect(document.title).toBe("workspaces — vmn-exp");
    rerender({ title: "ml-repo — vmn-exp" });
    expect(document.title).toBe("ml-repo — vmn-exp");
  });
});
