import { artifactUrl } from "../api";
import type { ExperimentDetail } from "../types";
import { hasMedia } from "../util/media";
import MediaImages from "../components/MediaImages";
import MediaTable from "../components/MediaTable";
import RunHistograms from "../components/RunHistograms";
import Disclosure from "../components/Disclosure";

/** The run page's Media section (logged images, tables and histograms),
 *  open by default since it shows only when there is media. */
export default function RunMediaSection({ ws, app, detail }: {
  ws: string; app: string; detail: ExperimentDetail;
}) {
  if (!hasMedia(detail)) return null;
  const verstr = detail.metadata.verstr;
  const url = (path: string) => artifactUrl(ws, app, verstr, path);
  return (
    <Disclosure id="run-media" title="Media" defaultOpen className="media-card">
      {detail.media && <MediaImages media={detail.media} url={url} />}
      {detail.tables && Object.keys(detail.tables).length > 0 && (
        <MediaTable ws={ws} app={app} verstr={verstr} tables={detail.tables} />
      )}
      {detail.histograms_total && (
        <RunHistograms ws={ws} app={app} verstr={verstr} totals={detail.histograms_total}
          inline={detail.histograms} />
      )}
    </Disclosure>
  );
}
