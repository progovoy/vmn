/** An outer run's baseline chip (plan 28 N3): the server's text
 *  (`▼ best_value from 2024-12 (5 of 41 trade_date values worse than the
 *  baseline's p10)`), coloured by its state, its title naming the run it
 *  compares against; a link when given *href*. */
import { Link } from "react-router-dom";
import type { BaselineChipData, BaselineRef, BaselineSource } from "../apiBaseline";
import { fleetLabel } from "./fleetRows";

/** How the baseline was picked; *match* the fields it shares (unknown: "alike"). */
export function pickedText(source: BaselineSource, match?: readonly string[]): string {
  if (source === "pinned") return "pinned with the tag baseline=true";
  if (source === "to") return "chosen with to=";
  if (!match) return "the latest ended outer run alike";
  return match.length ? `the latest ended outer run with the same ${match.join(", ")}` : "the latest ended outer run beside it";
}

export const baselineTitle = (ref: BaselineRef) => `vs ${fleetLabel(ref)}, ${pickedText(ref.source)}`;

export default function BaselineChip({ chip, baseline, href }: {
  chip: BaselineChipData; baseline?: BaselineRef | null; href?: string;
}) {
  const className = `baseline-chip baseline-${chip.state}`;
  const title = baseline ? baselineTitle(baseline) : undefined;
  if (href) return <Link className={className} to={href} title={title}>{chip.text}</Link>;
  return <span className={className} title={title}>{chip.text}</span>;
}
