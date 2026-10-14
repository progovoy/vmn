/** A line of parts joined by dots, each toned part in its status colour
 *  (a group's counts, the job header's progress). */
import { Fragment, type AriaAttributes } from "react";
import type { TonePart } from "../util/toneParts";
import "./toneParts.css";

export default function ToneParts({ parts, className, title, ...aria }: {
  parts: readonly TonePart[]; className?: string; title?: string;
} & AriaAttributes) {
  return (
    <span className={className ? `tone-parts ${className}` : "tone-parts"} title={title} {...aria}>
      {parts.map((p, i) => (
        <Fragment key={i}>
          {i > 0 && <span aria-hidden="true"> · </span>}
          <span className={p.tone && `tone-${p.tone}`}>{p.text}</span>
        </Fragment>
      ))}
    </span>
  );
}
