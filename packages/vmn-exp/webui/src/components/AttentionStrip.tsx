import { Fragment } from "react";
import { Link, useLocation } from "react-router-dom";
import type { AppStatus } from "../shell/contracts";
import { attentionParts } from "../util/attention";
import "./AttentionStrip.css";

/** Above the board: `⚠ 40 stuck · 3 failed in 24h · 12 running`, each part
 *  a link that filters the board to those runs (plan 20 C6). Hidden while
 *  nothing needs attention. *onFollow* runs after a part is clicked, so the
 *  filter bar can re-read the URL. */
export default function AttentionStrip({ status, now = Date.now(), onFollow }: {
  status?: AppStatus | null;
  now?: number;
  onFollow?: () => void;
}) {
  const { search } = useLocation();
  const parts = status ? attentionParts(status, search, now) : [];
  if (!parts.length) return null;
  return (
    <div className="attention-strip" role="status">
      <span className="attention-icon" aria-hidden="true">⚠</span>
      {parts.map((p, i) => (
        <Fragment key={p.key}>
          {i > 0 && <span className="attention-sep" aria-hidden="true"> · </span>}
          <Link className={`attention-${p.key}`} to={{ search: p.search }} title={p.title} onClick={onFollow}>
            {p.text}
          </Link>
        </Fragment>
      ))}
    </div>
  );
}
