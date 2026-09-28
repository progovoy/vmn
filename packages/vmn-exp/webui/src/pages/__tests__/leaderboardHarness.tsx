/** Shared rendering for the leaderboard suites that run under a real query
 *  client (so cache behaviour — Back, prefetch — is observable). */
import { render } from "@testing-library/react";
import { QueryClientProvider, type QueryClient } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { createQueryClient } from "../../queryClient";
import type { ExperimentRow } from "../../types";
import Leaderboard from "../Leaderboard";

export function row(i: number, extra: Partial<ExperimentRow> = {}): ExperimentRow {
  return {
    idx: i,
    verstr: `0.0.${i}-dev.x`,
    code_verstr: `0.0.${i}`,
    timestamp: new Date(Date.now() - i * 60_000).toISOString(),
    note: null,
    branch: "main",
    base_version: "0.0.1",
    user_meta: null,
    params: {},
    metrics: {},
    status: "succeeded",
    ...extra,
  };
}

export const page = (rows: ExperimentRow[], total?: number) =>
  Object.assign([...rows], { total: total ?? rows.length });

/** The current URL, readable from the test. */
export const location = { search: "", pathname: "" };
function LocationProbe() {
  const loc = useLocation();
  location.search = loc.search;
  location.pathname = loc.pathname;
  return null;
}

function RunStub() {
  const navigate = useNavigate();
  return <button onClick={() => navigate(-1)}>go-back</button>;
}

export const urlParams = () => new URLSearchParams(location.search);

export function renderBoard(path = "/ws/test/app/my-app", client: QueryClient = createQueryClient()) {
  const utils = render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <LocationProbe />
        <Routes>
          <Route path="/ws/:ws/app/:app" element={<Leaderboard />} />
          <Route path="/ws/:ws/app/:app/run/:verstr" element={<RunStub />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { ...utils, client };
}
