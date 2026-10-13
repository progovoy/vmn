import type { ReactNode } from "react";
import { useRovingToolbar } from "../hooks/useRovingToolbar";

/** The controls inside the search box (the similar toggle, the query help's
 *  `?`): one toolbar, one Tab stop, the arrow keys move between them. */
export default function SearchTools({ children }: { children: ReactNode }) {
  const roving = useRovingToolbar<HTMLSpanElement>();
  return (
    <span className="search-tools" role="toolbar" aria-label="Search options" {...roving}>
      {children}
    </span>
  );
}
