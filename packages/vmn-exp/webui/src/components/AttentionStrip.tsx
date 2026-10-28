import { Fragment } from "react";
import { Link, useLocation } from "react-router-dom";
import type { AppStatus } from "../shell/contracts";
import { attentionParts, type AttentionPart } from "../util/attention";
import "./AttentionStrip.css";

/** A configured part (plan 28 P1) is coloured by its level. */
const partClass = (p: AttentionPart) => `attention-${p.level ?? p.key}`;

/** Above the board: `⚠ 40 stuck · 3 failed in 24h · 2 unstable · 12
 *  running`, each part a link that filters the board to those runs (plan 20
 *  C6). Hidden while nothing needs attention. *from* is the search the links
 *  start from (another view's or tab's), else the page's own. *onFollow*
 *  runs after a part is clicked, so the filter bar can re-read the URL. */
export default function AttentionStrip({ status, now = Date.now(), from, onFollow }: {
  status?: AppStatus | null;
  now?: number;
  from?: string;
  onFollow?: () => void;
}) {
  const { search } = useLocation();
  const parts = status ? attentionParts(status, from ?? search, now) : [];
  if (!parts.length) return null;
  return (
    <div className="attention-strip" role="status">
      <span className="attention-icon" aria-hidden="true">⚠</span>
      {parts.map((p, i) => (
        <Fragment key={p.key}>
          {i > 0 && <span className="attention-sep" aria-hidden="true"> · </span>}
          <Link className={partClass(p)} to={{ search: p.search }} title={p.title} onClick={onFollow}>
            {p.text}
          </Link>
        </Fragment>
      ))}
    </div>
  );
}
