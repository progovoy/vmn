import { artifactUrl } from "../api";
import type { ExperimentDetail } from "../types";
import { hasMedia } from "../util/media";
import MediaHistograms from "../components/MediaHistograms";
import MediaImages from "../components/MediaImages";
import MediaTable from "../components/MediaTable";
import RunHistograms from "../components/RunHistograms";

/** The run page's Media card: logged images, tables and histograms. */
export default function RunMediaSection({ ws, app, detail }: {
  ws: string; app: string; detail: ExperimentDetail;
}) {
  if (!hasMedia(detail)) return null;
  const verstr = detail.metadata.verstr;
  const url = (path: string) => artifactUrl(ws, app, verstr, path);
  return (
    <div className="card media-card" style={{ marginBottom: 16 }}>
      <div className="eyebrow">media</div>
      {detail.media && <MediaImages media={detail.media} url={url} />}
      {detail.tables && Object.keys(detail.tables).length > 0 && (
        <MediaTable ws={ws} app={app} verstr={verstr} tables={detail.tables} />
      )}
      {detail.histograms_total ? (
        <RunHistograms ws={ws} app={app} verstr={verstr} totals={detail.histograms_total} />
      ) : detail.histograms && (
        <MediaHistograms histograms={detail.histograms} />
      )}
    </div>
  );
}
