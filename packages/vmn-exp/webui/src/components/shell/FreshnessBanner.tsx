/** Above an app's pages while the index serves data older than the server's
 *  threshold: how old, and the sync's progress — or, when the background
 *  refresh does not complete, an alert (util/freshness.ts). */
import { freshnessBanner, type Freshness } from "../../util/freshness";
import "./FreshnessBanner.css";

export default function FreshnessBanner({ freshness }: { freshness?: Freshness }) {
  const banner = freshnessBanner(freshness);
  if (!banner) return null;
  return (
    <div className={`freshness-banner ${banner.kind}`} role={banner.kind === "error" ? "alert" : "status"}>
      {banner.text}
    </div>
  );
}
