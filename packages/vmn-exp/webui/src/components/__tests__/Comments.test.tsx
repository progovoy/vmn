import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderWithClient } from "../../test-utils";

vi.mock("../../apiReports", async (orig) => ({
  ...(await orig<typeof import("../../apiReports")>()),
  apiReports: {
    listComments: vi.fn(), addComment: vi.fn(), editComment: vi.fn(), deleteComment: vi.fn(),
  },
}));

import { apiReports } from "../../apiReports";
import Comments from "../Comments";

const m = apiReports as unknown as Record<string, ReturnType<typeof vi.fn>>;
const T = "run:app:1.0.0";

const COMMENTS = [
  { id: "c1", ts: "2026-01-01T00:00:00Z", author: "ann", text: "**bold** ![x](http://e/x.png)",
    reply_to: null, anchor: null, resolved: false, deleted: false },
  { id: "c2", ts: "2026-01-01T01:00:00Z", author: "bob", text: "reply", reply_to: "c1",
    anchor: null, resolved: false, deleted: false },
  { id: "c3", ts: "2026-01-01T02:00:00Z", author: "bob", text: null, reply_to: null,
    anchor: null, resolved: false, deleted: true },
];

beforeEach(() => {
  vi.clearAllMocks();
  m.listComments.mockResolvedValue({ comments: COMMENTS, me: "ann" });
  for (const k of ["addComment", "editComment", "deleteComment"]) m[k].mockResolvedValue({});
});

const comment = async (id: string) => within(await screen.findByTestId(`comment-${id}`));

describe("Comments", () => {
  it("renders the thread with replies nested and a markdown subset", async () => {
    renderWithClient(<Comments ws="w" target={T} />);
    const c1 = await comment("c1");
    expect(c1.getByText("bold").tagName).toBe("STRONG");
    expect(document.querySelector(".comments img")).toBeNull();
    expect(c1.getByTestId("comment-c2")).toBeTruthy();
    expect(screen.getByText("deleted")).toBeTruthy();
  });

  it("posts a new comment and a reply", async () => {
    renderWithClient(<Comments ws="w" target={T} />);
    await comment("c1");
    fireEvent.change(screen.getByLabelText("New comment"), { target: { value: "hello" } });
    fireEvent.click(screen.getByRole("button", { name: "Comment" }));
    await waitFor(() => expect(m.addComment).toHaveBeenCalledWith("w", { target: T, text: "hello" }));
    const c1 = await comment("c1");
    fireEvent.click(c1.getAllByRole("button", { name: "Reply" })[0]);
    fireEvent.change(screen.getByLabelText("Reply"), { target: { value: "yo" } });
    fireEvent.click(screen.getByRole("button", { name: "Send reply" }));
    await waitFor(() => expect(m.addComment).toHaveBeenCalledWith("w", { target: T, text: "yo", reply_to: "c1" }));
  });

  it("lets only the author edit or delete, and anyone resolve", async () => {
    renderWithClient(<Comments ws="w" target={T} />);
    const c2 = within(await screen.findByTestId("comment-c2"));
    expect(c2.queryByRole("button", { name: "Edit" })).toBeNull();
    const own = screen.getByTestId("comment-c1");
    const header = within(own.querySelector(".comment-actions") as HTMLElement);
    fireEvent.click(header.getByRole("button", { name: "Edit" }));
    fireEvent.change(screen.getByLabelText("Edit comment"), { target: { value: "new" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(m.editComment).toHaveBeenCalledWith("w", T, "c1", { text: "new" }));
    fireEvent.click(header.getByRole("button", { name: "Resolve" }));
    await waitFor(() => expect(m.editComment).toHaveBeenCalledWith("w", T, "c1", { resolved: true }));
    vi.spyOn(window, "confirm").mockReturnValue(true);
    fireEvent.click(header.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(m.deleteComment).toHaveBeenCalledWith("w", T, "c1"));
  });

  it("lets everyone edit without a known user (standalone = admin)", async () => {
    m.listComments.mockResolvedValue({ comments: COMMENTS });
    renderWithClient(<Comments ws="w" target={T} />);
    const c2 = within(await screen.findByTestId("comment-c2"));
    expect(c2.getByRole("button", { name: "Edit" })).toBeTruthy();
  });

  it("filters to one anchor and posts with it", async () => {
    m.listComments.mockResolvedValue({ comments: [
      { ...COMMENTS[0], anchor: { panel: "loss" } }, { ...COMMENTS[1], reply_to: null },
    ] });
    renderWithClient(<Comments ws="w" target="report:r1" anchor={{ panel: "loss" }} />);
    await comment("c1");
    expect(screen.queryByTestId("comment-c2")).toBeNull();
    fireEvent.change(screen.getByLabelText("New comment"), { target: { value: "p" } });
    fireEvent.click(screen.getByRole("button", { name: "Comment" }));
    await waitFor(() => expect(m.addComment).toHaveBeenCalledWith("w",
      { target: "report:r1", text: "p", anchor: { panel: "loss" } }));
  });
});
