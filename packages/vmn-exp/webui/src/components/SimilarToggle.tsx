/** The search box's "similar" mode switch: the box then describes a run to
 *  find runs like it, and the bar's tokens keep filtering. */
export default function SimilarToggle({ on, onToggle }: { on: boolean; onToggle: () => void }) {
  return (
    <button
      type="button"
      className="status-toggle similar-toggle"
      aria-pressed={on}
      title="find runs similar to a description (intent, name, note, tags, commits)"
      onClick={onToggle}
    >
      similar
    </button>
  );
}
