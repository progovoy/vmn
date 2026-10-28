/** An outer run's baseline chip (plan 28 N3): the server's text
 *  (`▼ best_value from 2024-12 (5 of 41 trade_date values worse than the
 *  baseline's p10)`), coloured by its state, its title naming the run it
 *  compares against; a link when given *href*. */
import { Link } from "react-router-dom";
import type { BaselineChipData, BaselineRef, BaselineSource } from "../apiBaseline";

const PICKED: Record<BaselineSource, string> = {
  latest: "the latest ended outer run alike",
  pinned: "pinned with the tag baseline=true",
  to: "chosen",
};

/** `@12 wf_41aa`: a run's index and name (its verstr without a name). */
export const baselineLabel = (ref: BaselineRef) =>
  [ref.idx != null ? `@${ref.idx}` : null, ref.name ?? (ref.idx == null ? ref.verstr : null)]
    .filter(Boolean).join(" ");

export const baselineTitle = (ref: BaselineRef) => `vs ${baselineLabel(ref)}, ${PICKED[ref.source]}`;

export default function BaselineChip({ chip, baseline, href }: {
  chip: BaselineChipData; baseline?: BaselineRef | null; href?: string;
}) {
  const className = `baseline-chip baseline-${chip.state}`;
  const title = baseline ? baselineTitle(baseline) : undefined;
  if (href) return <Link className={className} to={href} title={title}>{chip.text}</Link>;
  return <span className={className} title={title}>{chip.text}</span>;
}
