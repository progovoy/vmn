/** Shared run-page fixture for the plan 20 B5 layout and flow tests: a run
 *  with every section the page can show. The tests mock the API modules
 *  themselves; this file only builds payloads and renders the page. */
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { renderWithClient } from "../../test-utils";
import type { ExperimentDetail, LogEntry, RunStatus } from "../../types";
import Run from "../Run";

export const RUN = "0.0.1-dev.layout";

export function runStatus(extra: Partial<RunStatus> = {}): RunStatus {
  return {
    status: "succeeded", exit_code: 0, started_at: "2026-01-01T12:00:00Z",
    finished_at: "2026-01-01T12:05:00Z", heartbeat: "2026-01-01T12:04:59Z",
    duration_sec: 300, pid: 4242, host: "gpu0", command: ["python", "train.py"],
    stale_sec: null, parent: null, children: [], kind: "single", depth: 0,
    tree_status: null, last_metric_at: null, ...extra,
  };
}

export const logEntries = (n: number): LogEntry[] =>
  Array.from({ length: n }, (_, i) => ({
    timestamp: `2026-01-01T12:00:${String(i).padStart(2, "0")}Z`, type: "note", text: `entry-${i}`,
  }));

export function fullDetail(extra: Partial<ExperimentDetail> = {}): ExperimentDetail {
  return {
    metadata: {
      verstr: RUN, name: "layout-run", branch: "main", base_version: "0.0.1",
      base_commit: "abc1234567890", timestamp: "2026-01-01T12:00:00Z", note: "",
    },
    idx: 7,
    params: { lr: 0.1, model: "resnet" },
    metrics: { loss: 0.2, lr: 0.1 },
    metric_summary: { loss: { last: 0.2, min: 0.2, max: 1 } },
    series: { loss: [{ step: 0, value: 1, ts: null }, { step: 1, value: 0.2, ts: null }] },
    log_tail: logEntries(14),
    log_total: 14,
    patches: {},
    status: runStatus(),
    artifacts: [{ name: "outputs/output.log", size: 4 }, { name: "model.pt", size: 10 }],
    env: { python: "3.11.0", platform: "Linux/x86_64", packages: { torch: "2.1" } },
    media: { sample: [{ step: 0, path: "outputs/media/sample/0.png" }] },
    ...extra,
  } as ExperimentDetail;
}

function Where() {
  const { search, hash } = useLocation();
  return <output data-testid="where">{search}{hash}</output>;
}

export function renderRunPage(path = `/ws/test/app/my-app/run/${RUN}`) {
  return renderWithClient(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/ws/:ws/app/:app/run/:verstr" element={<><Run /><Where /></>} />
      </Routes>
    </MemoryRouter>,
  );
}

/** The page's h2 section headings, in document order. */
export const sectionHeadings = () =>
  [...document.querySelectorAll("h2")].map((h) => h.textContent?.trim());
