/** ⌘K "go to run" (plan 23 S8/W11): `GET .../search?text=&limit=` over
 *  every run of an app — `@N`, name, verstr prefix, tags, notes — each hit
 *  with its job (`root`, `root_name`). */
import { appTag, get } from "./http";

export interface RunSearchHit {
  verstr: string;
  idx: number;
  name: string | null;
  status: string | null;
  /** Its top-level ancestor (its job); null for a top-level run. */
  root: string | null;
  root_name: string | null;
  /** The field that matched (`idx` for `@N`). */
  match: string;
}

export const searchRuns = (ws: string, app: string, text: string, limit: number) =>
  get<{ results: RunSearchHit[] }>(
    `/workspaces/${ws}/apps/${appTag(app)}/search?${new URLSearchParams({ text, limit: String(limit) })}`,
  ).then((body) => body.results);
