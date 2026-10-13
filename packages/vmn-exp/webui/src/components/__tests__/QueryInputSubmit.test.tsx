import { describe, it, expect, vi } from "vitest";
import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import QueryInput from "../QueryInput";

function Box({ onSubmit }: { onSubmit: () => void }) {
  const [text, setText] = useState("");
  return <QueryInput value={text} onChange={setText} facets={{ metric_keys: ["loss"] }} onSubmit={onSubmit} />;
}

const box = () => screen.getByLabelText("Filter query") as HTMLInputElement;

describe("QueryInput with onSubmit", () => {
  it("Enter submits while suggestions are merely shown", () => {
    const onSubmit = vi.fn();
    render(<Box onSubmit={onSubmit} />);
    fireEvent.change(box(), { target: { value: "metrics.l", selectionStart: 9 } });
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    fireEvent.keyDown(box(), { key: "Enter" });
    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(box().value).toBe("metrics.l");
  });

  it("Enter picks the suggestion the arrows moved to, Tab picks the first", () => {
    const onSubmit = vi.fn();
    render(<Box onSubmit={onSubmit} />);
    fireEvent.change(box(), { target: { value: "metrics.l", selectionStart: 9 } });
    fireEvent.keyDown(box(), { key: "ArrowDown" });
    fireEvent.keyDown(box(), { key: "ArrowUp" });
    fireEvent.keyDown(box(), { key: "Enter" });
    expect(onSubmit).not.toHaveBeenCalled();
    expect(box().value).toBe("metrics.loss ");
    fireEvent.change(box(), { target: { value: "metrics.l", selectionStart: 9 } });
    fireEvent.keyDown(box(), { key: "Tab" });
    expect(box().value).toBe("metrics.loss ");
  });
});
