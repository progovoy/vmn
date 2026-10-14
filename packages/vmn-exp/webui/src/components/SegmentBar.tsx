/** A run bar in the status colours (group headers, Jobs rows, the job
 *  header): one span per state at its share; the track left over is the
 *  runs not finished nor running. The container's class sets its size; each
 *  segment also gets `<className>-seg`. */
import type { AriaAttributes, AriaRole } from "react";
import "./segmentBar.css";

export interface BarSegment { tone: string; pct: number }

export default function SegmentBar({ segments, className, role, ...aria }: {
  segments: readonly BarSegment[]; className: string; role?: AriaRole;
} & AriaAttributes) {
  return (
    <span className={`seg-bar ${className}`} role={role} {...aria}>
      {segments.map((sg) => (
        <span
          key={sg.tone} className={`bar-seg ${className}-seg tone-${sg.tone}`} data-tone={sg.tone}
          style={{ width: `${sg.pct}%` }}
        />
      ))}
    </span>
  );
}
