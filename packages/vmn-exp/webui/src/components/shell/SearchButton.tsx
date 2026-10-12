import { Icon } from "./icons";
import "./Topbar.css";

const shortcut = () => (/Mac|iP(hone|ad)/.test(navigator.platform) ? "⌘K" : "Ctrl K");

/** Opens the command palette. Icon-only below 600px; the name keeps the key. */
export default function SearchButton({ onSearch }: { onSearch: () => void }) {
  const key = shortcut();
  return (
    <button type="button" className="search-btn" aria-label={`Search (${key})`} onClick={onSearch}>
      <Icon name="search" />
      <span className="search-label">Search</span>
      <kbd className="search-key">{key}</kbd>
    </button>
  );
}
