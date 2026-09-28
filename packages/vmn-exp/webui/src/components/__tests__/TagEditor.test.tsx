import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";

vi.mock("../../api", () => ({
  api: { action: vi.fn(), job: vi.fn() },
}));

import { api } from "../../api";
import { createQueryClient } from "../../queryClient";
import { rowsKey, runKey } from "../../queries";
import TagEditor from "../TagEditor";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const V = "0.0.1-dev.a";
const running = { id: "j1", status: "running", command: [], exit_code: null, log: "", noop: false };
const done = (status: string) => ({ ...running, status, exit_code: status === "succeeded" ? 0 : 1 });

function setup(tags: Record<string, string> = { team: "vision" }) {
  const client = createQueryClient();
  client.setQueryData(runKey("w", "app", V), { metadata: { verstr: V, tags }, metrics: {}, series: {}, patches: {} });
  client.setQueryData(rowsKey("w", "app", {}), { rows: [{ verstr: V, tags, metrics: {} }], total: 1 });
  render(
    <QueryClientProvider client={client}>
      <TagEditor ws="w" app="app" verstr={V} tags={tags} />
    </QueryClientProvider>,
  );
  return client;
}

const addTag = (text: string) => {
  fireEvent.click(screen.getByRole("button", { name: "+ tag" }));
  const input = screen.getByLabelText("New tag");
  fireEvent.change(input, { target: { value: text } });
  fireEvent.keyDown(input, { key: "Enter" });
};

beforeEach(() => {
  vi.clearAllMocks();
  m.action.mockResolvedValue(running);
});

describe("TagEditor", () => {
  it("shows the run's tags as chips", () => {
    setup();
    expect(screen.getByText("team: vision")).toBeInTheDocument();
  });

  it("adds a tag at once and commits it to the caches when the job succeeds", async () => {
    m.job.mockResolvedValue(done("succeeded"));
    const client = setup();
    addTag("stage=prod");
    expect(screen.getByText("stage: prod")).toBeInTheDocument();
    expect(m.action).toHaveBeenCalledWith("w", "app", "exp_tag", { verstr: V, set: { stage: "prod" }, remove: [] });
    await waitFor(() =>
      expect((client.getQueryData(runKey("w", "app", V)) as { metadata: { tags: object } }).metadata.tags)
        .toEqual({ team: "vision", stage: "prod" }),
    );
    const rows = client.getQueryData(rowsKey("w", "app", {})) as { rows: { tags: object }[] };
    expect(rows.rows[0].tags).toEqual({ team: "vision", stage: "prod" });
    expect(screen.getByText("stage: prod")).toBeInTheDocument();
  });

  it("removes a tag through --remove", async () => {
    m.job.mockResolvedValue(done("succeeded"));
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Remove tag team" }));
    expect(screen.queryByText("team: vision")).toBeNull();
    expect(m.action).toHaveBeenCalledWith("w", "app", "exp_tag", { verstr: V, set: {}, remove: ["team"] });
  });

  it("puts the old tags back when the job fails", async () => {
    m.job.mockResolvedValue(done("failed"));
    setup();
    addTag("stage=prod");
    expect(screen.getByText("stage: prod")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("tags not saved")).toBeInTheDocument());
    expect(screen.queryByText("stage: prod")).toBeNull();
    expect(screen.getByText("team: vision")).toBeInTheDocument();
  });

  it("refuses a malformed tag without a request", () => {
    setup();
    addTag("-bad=x");
    expect(screen.getByRole("alert")).toHaveTextContent(/key=value/);
    expect(m.action).not.toHaveBeenCalled();
  });

  it("accepts a bare key as a tag with an empty value", () => {
    setup({});
    addTag("golden");
    expect(m.action).toHaveBeenCalledWith("w", "app", "exp_tag", { verstr: V, set: { golden: "" }, remove: [] });
    expect(screen.getByText("golden")).toBeInTheDocument();
  });
});
