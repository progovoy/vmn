/** The shell's reads: git context and app status. Kept apart from api.ts so
 *  shell tests can mock them on their own. */
import { get } from "./http";
import type { AppStatus, GitContext } from "./shell/contracts";

export const apiShell = {
  gitContext: (ws: string) => get<GitContext>(`/workspaces/${ws}/git`),
  /** *tag* is the app in URL tag form; *scope* an outer run, for its subtree. */
  appStatus: (ws: string, tag: string, scope?: string) =>
    get<AppStatus>(`/workspaces/${ws}/apps/${tag}/experiments-status${scope ? `?scope=${encodeURIComponent(scope)}` : ""}`),
};
