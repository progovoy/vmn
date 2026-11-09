/** An outer run's baseline chip (plan 28 N3): the server's text
 *  (`▼ best_value from 2024-12 (5 of 41 trade_date values worse than the
 *  baseline's p10)`), coloured by its state, its title naming the run it
 *  compares against; a link when given *href*. */
import { Link } from "react-router-dom";
import type { BaselineChipData, BaselineRef, BaselineSource } from "../apiBaseline";
import { fleetLabel } from "./fleetRows";

/** ` with the same a, b and a different c` (plan 34 §2), empty for no fields. */
export function ruleText(match: readonly string[], differ: readonly string[] = []): string {
  const parts = [
    match.length ? `the same ${match.join(", ")}` : "",
    differ.length ? `a different ${differ.join(", ")}` : "",
  ].filter(Boolean);
  return parts.length ? ` with ${parts.join(" and ")}` : "";
}

/** How the baseline was picked; *match* the fields it shares and *differ*
 *  the ones it does not (unknown: "alike"). */
export function pickedText(source: BaselineSource, match?: readonly string[], differ?: readonly string[]): string {
  if (source === "pinned") return "pinned with the tag baseline=true";
  if (source === "to") return "chosen with to=";
  if (!match) return "the latest ended outer run alike";
  return `the latest ended outer run${ruleText(match, differ) || " beside it"}`;
}

export const baselineTitle = (ref: BaselineRef) => `vs ${fleetLabel(ref)}, ${pickedText(ref.source)}`;

/** ` · 5 of 39 paired` when some keys lack a value on a side, else nothing. */
const pairedText = ({ paired, total }: BaselineChipData) =>
  paired != null && total != null && paired < total ? ` · ${paired} of ${total} paired` : "";

export default function BaselineChip({ chip, baseline, href }: {
  chip: BaselineChipData; baseline?: BaselineRef | null; href?: string;
}) {
  const className = `baseline-chip baseline-${chip.state}`;
  const title = baseline ? baselineTitle(baseline) : undefined;
  const text = chip.text + pairedText(chip);
  if (href) return <Link className={className} to={href} title={title}>{text}</Link>;
  return <span className={className} title={title}>{text}</span>;
}
