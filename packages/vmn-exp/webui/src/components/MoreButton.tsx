/** A group's `+N more` button (the board's rows and cards, the Jobs view):
 *  disabled while its page loads, an alert offering a retry when it failed. */
import { MORE_TEXT } from "../pages/groupHeaderText";
import type { GroupMoreItem } from "../util/groupItems";

export default function MoreButton({ item, onMore }: { item: GroupMoreItem; onMore: (key: string) => void }) {
  return (
    <button
      type="button" className="group-more-btn" disabled={item.state === "loading"}
      role={item.state === "error" ? "alert" : undefined} onClick={() => onMore(item.key)}
    >
      {MORE_TEXT[item.state](item.remaining)}
    </button>
  );
}
