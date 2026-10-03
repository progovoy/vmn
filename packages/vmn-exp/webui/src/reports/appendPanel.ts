/** Append a panel block to a report as a new revision, rebasing on conflicts. */
import { apiReports } from "../apiReports";
import type { HttpError } from "../http";
import type { PanelSpec } from "./panelSpec";
import { insertPanelBlock, specToBlock } from "./panelBlocks";

const MAX_ATTEMPTS = 3;

/** Returns the new revision number. A 409 means someone saved meanwhile:
 *  refetch the latest body and append to that instead. */
export async function appendPanel(ws: string, rid: string, spec: PanelSpec): Promise<number> {
  for (let attempt = 1; ; attempt++) {
    const { rev, body } = await apiReports.getReport(ws, rid);
    const next = insertPanelBlock(body, body.length, spec as Record<string, unknown>);
    try {
      return (await apiReports.saveRevision(ws, rid, { base: rev, body: next, message: `add panel ${spec.id}` })).rev;
    } catch (err) {
      if ((err as HttpError).status !== 409 || attempt >= MAX_ATTEMPTS) throw err;
    }
  }
}

export async function createReportWithPanel(ws: string, title: string, spec: PanelSpec): Promise<string> {
  return (await apiReports.createReport(ws, { title, body: specToBlock(spec as Record<string, unknown>) })).rid;
}
