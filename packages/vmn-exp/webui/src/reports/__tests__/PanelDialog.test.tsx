import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import PanelDialog from "../PanelDialog";

const change = (label: string, value: string) =>
  fireEvent.change(screen.getByLabelText(label), { target: { value } });

describe("PanelDialog", () => {
  it("builds a curves spec from a query", () => {
    const onSubmit = vi.fn();
    render(<PanelDialog onSubmit={onSubmit} onClose={() => {}} />);
    change("Type", "curves");
    change("App", "trainer");
    change("Filter query", "status = succeeded");
    change("Keys", "loss, acc");
    fireEvent.click(screen.getByRole("button", { name: "Insert" }));
    const spec = onSubmit.mock.calls[0][0];
    expect(spec).toMatchObject({ v: 1, type: "curves", app: "trainer", runs: { query: "status = succeeded" }, keys: ["loss", "acc"] });
    expect(typeof spec.id).toBe("string");
  });

  it("builds a single-run spec from pinned verstrs", () => {
    const onSubmit = vi.fn();
    render(<PanelDialog onSubmit={onSubmit} onClose={() => {}} />);
    change("Type", "media");
    change("App", "a");
    fireEvent.click(screen.getByLabelText("Pinned runs"));
    change("Verstrs", "1.0.0-dev.abc");
    change("Key", "img");
    fireEvent.click(screen.getByRole("button", { name: "Insert" }));
    expect(onSubmit.mock.calls[0][0]).toMatchObject({ type: "media", runs: { verstrs: ["1.0.0-dev.abc"] }, key: "img" });
  });

  it("shows validation errors and does not submit", () => {
    const onSubmit = vi.fn();
    render(<PanelDialog onSubmit={onSubmit} onClose={() => {}} />);
    change("Type", "bar");
    change("App", "a");
    change("Filter query", "(x = 1");
    fireEvent.click(screen.getByRole("button", { name: "Insert" }));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getAllByRole("alert").length).toBeGreaterThan(0);
  });

  it("edits an existing spec keeping its id and extra fields", () => {
    const onSubmit = vi.fn();
    const initial = { v: 1, id: "p1", type: "bar", app: "a", runs: { query: "x = 1" }, metric: "m", title: "T" };
    render(<PanelDialog initial={initial} onSubmit={onSubmit} onClose={() => {}} />);
    expect(screen.getByLabelText("Metric")).toHaveValue("m");
    change("Metric", "m2");
    fireEvent.click(screen.getByRole("button", { name: "Update" }));
    expect(onSubmit.mock.calls[0][0]).toEqual({ ...initial, metric: "m2" });
  });
});
