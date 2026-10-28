/** A tree node's ▸/▾ expander (plan 28 N6): the outer run tree's nodes and
 *  an Outer runs row's tree, labelled `expand <name>` / `collapse <name>`. */
export default function TreeToggle({ label, expanded, onToggle, tabIndex }: {
  label: string;
  expanded: boolean;
  onToggle: () => void;
  /** -1 inside a tree grid, whose rows hold the tab stop. */
  tabIndex?: number;
}) {
  return (
    <button
      type="button" className="tree-toggle" tabIndex={tabIndex} aria-expanded={expanded}
      aria-label={`${expanded ? "collapse" : "expand"} ${label}`} onClick={onToggle}
    >
      {expanded ? "▾" : "▸"}
    </button>
  );
}
