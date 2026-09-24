import type { CSSProperties } from "react";

/** The floating hover box every chart shares. */
export const TOOLTIP_STYLE: CSSProperties = {
  position: "absolute",
  pointerEvents: "none",
  background: "var(--panel-2)",
  border: "1px solid var(--line)",
  borderRadius: 8,
  color: "var(--text)",
  fontSize: 11.5,
  padding: "6px 8px",
  zIndex: 5,
  whiteSpace: "nowrap",
};
