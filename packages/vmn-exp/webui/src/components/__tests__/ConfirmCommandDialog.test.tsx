import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import ConfirmCommandDialog from "../ConfirmCommandDialog";

function renderDialog(extra: Partial<Parameters<typeof ConfirmCommandDialog>[0]> = {}) {
  const onConfirm = vi.fn();
  const onCancel = vi.fn();
  render(
    <ConfirmCommandDialog
      title="Goto 1.2.0?"
      command="vmn goto -v 1.2.0 ml_app"
      note="Other apps in this repo are untouched."
      confirmLabel="Run goto"
      onConfirm={onConfirm}
      onCancel={onCancel}
      {...extra}
    />,
  );
  return { onConfirm, onCancel };
}

describe("ConfirmCommandDialog", () => {
  it("is a labelled modal dialog showing the exact command and the note", () => {
    renderDialog();
    const dialog = screen.getByRole("dialog", { name: "Goto 1.2.0?" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(screen.getByText("vmn goto -v 1.2.0 ml_app").tagName).toBe("CODE");
    expect(screen.getByText("Other apps in this repo are untouched.")).toBeInTheDocument();
  });

  it("focuses Cancel first, so Enter on open never runs the command", () => {
    renderDialog();
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
  });

  it("confirms only through the confirm button", () => {
    const { onConfirm, onCancel } = renderDialog();
    fireEvent.click(screen.getByRole("button", { name: "Run goto" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onCancel).not.toHaveBeenCalled();
  });

  it("cancels on Cancel, Escape and a backdrop click", () => {
    const { onConfirm, onCancel } = renderDialog();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    fireEvent.mouseDown(screen.getByRole("dialog").parentElement!);
    expect(onCancel).toHaveBeenCalledTimes(3);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("returns focus to the opener when it closes", () => {
    const opener = document.createElement("button");
    document.body.appendChild(opener);
    opener.focus();
    const { unmount } = render(
      <ConfirmCommandDialog title="t" command="vmn goto x" onConfirm={() => {}} onCancel={() => {}} />,
    );
    expect(opener).not.toHaveFocus();
    unmount();
    expect(opener).toHaveFocus();
    opener.remove();
  });
});
