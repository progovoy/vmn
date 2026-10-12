/** The topbar's one row: [menu] crumbs ── [read-only] [Search] [theme] [identity].
 *  It renders the contents of `<header class="topbar">`. */
import type { ReactNode } from "react";
import type { ShellContext } from "../../shell/contracts";
import ThemeToggle from "../ThemeToggle";
import IdentityChip from "./IdentityChip";
import SearchButton from "./SearchButton";
import { Icon } from "./icons";
import "./Topbar.css";

export default function Topbar({ ctx, crumbs, onSearch, onMenu, menuOpen, onSignOut }: {
  ctx: ShellContext;
  /** The rendered `<Crumbs/>`. */
  crumbs: ReactNode;
  onSearch: () => void;
  /** Set below 900px, where the sidebar is a drawer. */
  onMenu?: () => void;
  menuOpen?: boolean;
  onSignOut: () => void;
}) {
  return (
    <>
      {onMenu && (
        <button
          type="button" className="topbar-menu" aria-label="Open navigation"
          aria-expanded={Boolean(menuOpen)} aria-controls="sidebar" onClick={onMenu}
        >
          <Icon name="menu" />
        </button>
      )}
      <div className="topbar-crumbs">{crumbs}</div>
      <div className="topbar-right">
        {ctx.readOnly && (
          <span className="ro-badge" title={ctx.readOnlyReason ?? undefined}>read-only</span>
        )}
        <SearchButton onSearch={onSearch} />
        <ThemeToggle />
        <IdentityChip ctx={ctx} onSignOut={onSignOut} />
      </div>
    </>
  );
}
