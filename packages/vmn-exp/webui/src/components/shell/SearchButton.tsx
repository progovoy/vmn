import { TOUCH_QUERY, useMediaQuery } from "../../hooks/useMediaQuery";
import { Icon } from "./icons";
import "./Topbar.css";

const shortcut = () => (/Mac|iP(hone|ad)/.test(navigator.platform) ? "⌘K" : "Ctrl K");

/** Opens the command palette. Icon-only below 600px; the name keeps the key,
 *  except on a touch screen, which has no keyboard to press it on. */
export default function SearchButton({ onSearch }: { onSearch: () => void }) {
  const key = useMediaQuery(TOUCH_QUERY) ? null : shortcut();
  return (
    <button type="button" className="search-btn" aria-label={key ? `Search (${key})` : "Search"} onClick={onSearch}>
      <Icon name="search" />
      <span className="search-label">Search</span>
      {key && <kbd className="search-key">{key}</kbd>}
    </button>
  );
}
