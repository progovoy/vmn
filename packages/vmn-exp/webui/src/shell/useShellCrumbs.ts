/** The shell's wayfinding for the current route: crumbs, copy-as-CLI
 *  commands and the document title, all from one CrumbInput. */
import { useMemo } from "react";
import type { ReportDetail } from "../apiReports";
import type { CliCommand, Crumb, CrumbInput, ShellContext } from "./contracts";
import { cliFor } from "./cliCommands";
import { crumbsFor, isAppRoute } from "./crumbs";
import { titleFor } from "./titles";
import { useAppStatus } from "./useShellData";
import { useCacheRead, useRunLabel } from "./useRunLabel";

export function useShellCrumbs(ctx: ShellContext): { crumbs: Crumb[]; cli: CliCommand[]; title: string } {
  const routeId = ctx.override ?? ctx.routeId;
  const { ws, appTag, app, params, search, workspace } = ctx;
  const run = useRunLabel(ws, appTag, routeId === "run" ? params.verstr : undefined);
  const status = useAppStatus(ws, isAppRoute(routeId) ? appTag : undefined).data;
  const rid = routeId === "report" || routeId === "report-edit" ? params.rid : undefined;
  const reportTitle = useCacheRead((client) =>
    rid ? client.getQueryData<ReportDetail>(["report", ws, rid])?.title ?? "" : "");
  const storeUri = workspace?.kind === "store" ? workspace.store : undefined;
  const stuck = status?.counts.stuck;

  return useMemo(() => {
    const input: CrumbInput = {
      routeId, ws, app, appTag, params, search, run, reportTitle: reportTitle || undefined, storeUri,
    };
    return { crumbs: crumbsFor(input), cli: cliFor(input), title: titleFor(input, { stuck }) };
  }, [routeId, ws, app, appTag, params, search, run, reportTitle, storeUri, stuck]);
}
