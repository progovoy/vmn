/** The shell's reads: git context, app status and ref resolution. Kept apart
 *  from api.ts so shell tests can mock them on their own. */
import { get, type HttpError } from "./http";
import type { AppStatus, GitContext, RunLabel } from "./shell/contracts";
import type { ExperimentDetail } from "./types";

const appPath = (ws: string, tag: string) => `/workspaces/${ws}/apps/${tag}`;

export const apiShell = {
  gitContext: (ws: string) => get<GitContext>(`/workspaces/${ws}/git`),
  /** *tag* is the app in URL tag form. */
  appStatus: (ws: string, tag: string) =>
    get<AppStatus>(`${appPath(ws, tag)}/experiments-status`),
  /** The run a ref (`@N`, prefix, `latest`, verstr) names, or null when none does. */
  async resolveRef(ws: string, tag: string, ref: string): Promise<RunLabel | null> {
    try {
      const detail = await get<ExperimentDetail>(
        `${appPath(ws, tag)}/experiments/${encodeURIComponent(ref)}?series=false&max_points=2`,
      );
      return { verstr: detail.metadata.verstr, idx: detail.idx ?? null, name: detail.name ?? null };
    } catch (e) {
      if ((e as HttpError).status === 404) return null;
      throw e;
    }
  },
};
