/** Rendering the experiments page (plan 23 W1: Jobs | All runs) at its
 *  route, with the URL readable from the test. Mock `../../../api` first. */
import { render } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { createQueryClient } from "../../../queryClient";
import type { ExperimentRow } from "../../../types";
import { readPicks } from "../../../util/runSelection";
import { job } from "../../../util/__tests__/jobFixture";
import ExperimentsPage from "../ExperimentsPage";
import { WithTray } from "../../__tests__/withTray";

export const location = { search: "", pathname: "" };
/** The browser's Back button. */
export const nav = { back: () => {} };
function LocationProbe() {
  const loc = useLocation();
  const navigate = useNavigate();
  nav.back = () => navigate(-1);
  location.search = loc.search;
  location.pathname = loc.pathname;
  return null;
}
export const urlParams = () => new URLSearchParams(location.search);
/** The app's run selection (the tray's picks), which replaced the URL's `sel`. */
export const selection = (ws = "test", app = "my-app") => readPicks(ws, app).map((p) => p.verstr);

export function renderExperiments(path = "/ws/test/app/my-app") {
  const client = createQueryClient();
  const utils = render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <LocationProbe />
        <Routes>
          <Route path="/ws/:ws/app/:app" element={<WithTray><ExperimentsPage /></WithTray>} />
          <Route path="/ws/:ws/app/:app/run/:verstr" element={<div>run page</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { ...utils, client };
}

/** A top-level run: a job (with a summary) unless `job: null` is given. */
export function topRow(i: number, extra: Partial<ExperimentRow> = {}): ExperimentRow {
  return {
    idx: i,
    verstr: `0.0.${i}-dev.x`,
    code_verstr: `0.0.${i}`,
    timestamp: new Date(Date.now() - i * 3_600_000).toISOString(),
    started_at: new Date(Date.now() - i * 3_600_000).toISOString(),
    note: null,
    branch: "main",
    base_version: "0.0.1",
    params: {},
    metrics: {},
    status: "running",
    tree_status: "running",
    kind: "outer",
    depth: 0,
    root: null,
    job: job(),
    ...extra,
  };
}

/** A single top-level run (no children). */
export const singleRow = (i: number, extra: Partial<ExperimentRow> = {}) =>
  topRow(i, { kind: "single", status: "succeeded", tree_status: "succeeded", job: null, ...extra });

export const jobsPage = (rows: ExperimentRow[], total?: number) => ({ rows, total: total ?? rows.length });

export const notFound = () => Object.assign(new Error("nf"), { status: 404 });
