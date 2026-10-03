/** Entry of the exported-report bundle (plan 13 §6): renders one report
 *  revision from data inlined into the page, without any network. */
import "../styles.css";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { Markdown } from "./Markdown";
import Panel from "./Panel";
import { MediaUrlContext, type MediaUrl } from "./mediaUrl";
import type { PanelPayload } from "./publishedData";

export interface ExportData {
  title: string;
  rev: number;
  body: string;
  /** Published payload per panel id. */
  panels: Record<string, PanelPayload>;
  /** `vmn://<app>/<verstr>/<path>` -> data URI, for media within the cap. */
  media: Record<string, string>;
}

const DATA_ID = "vmn-report-data";

export function ExportedReport({ data }: { data: ExportData }) {
  const mediaUrl: MediaUrl = (_ws, app, verstr, path) => data.media[`vmn://${app}/${verstr}/${path}`] ?? "";
  const resolveMedia = (uri: string) => data.media[uri] ?? "";
  return (
    <MemoryRouter>
      <MediaUrlContext.Provider value={mediaUrl}>
        <Markdown source={data.body} resolveMedia={resolveMedia}
          renderPanel={(spec) => <Panel ws="" spec={spec} payload={data.panels[String(spec.id ?? "")] ?? null} />} />
      </MediaUrlContext.Provider>
    </MemoryRouter>
  );
}

export function mountExport(doc: Document) {
  const data = JSON.parse(doc.getElementById(DATA_ID)!.textContent!) as ExportData;
  createRoot(doc.getElementById("root")!).render(<ExportedReport data={data} />);
}

if (typeof document !== "undefined" && document.getElementById(DATA_ID)?.textContent) mountExport(document);
