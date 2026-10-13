import BoardShortcuts from "../components/BoardShortcuts";
import Segmented from "../components/Segmented";
import type { Density } from "../util/density";

const DENSITY_OPTIONS: readonly (readonly [Density, string])[] = [["comfortable", "Comfortable"], ["compact", "Compact"]];

/** The grid's own controls, at the end of its caption (the page head keeps
 *  its plan 20 C7 budget of controls above the table): the row density and
 *  the keyboard help. The phone's cards go without them. */
export default function BoardGridTools({ density, onDensity }: {
  density: Density;
  onDensity: (d: Density) => void;
}) {
  return (
    <span className="board-grid-tools">
      <Segmented label="Row density" options={DENSITY_OPTIONS} value={density} onChange={onDensity} />
      <BoardShortcuts />
    </span>
  );
}
