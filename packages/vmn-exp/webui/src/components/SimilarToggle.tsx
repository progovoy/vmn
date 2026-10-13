import ToggleChip from "./ToggleChip";

/** The search box's "similar" mode switch: the box then describes a run to
 *  find runs like it, and the bar's tokens keep filtering. */
export default function SimilarToggle({ on, onToggle }: { on: boolean; onToggle: () => void }) {
  return (
    <ToggleChip
      className="similar-toggle"
      pressed={on}
      title="find runs similar to a description (intent, name, note, tags, commits)"
      onChange={onToggle}
    >
      similar
    </ToggleChip>
  );
}
