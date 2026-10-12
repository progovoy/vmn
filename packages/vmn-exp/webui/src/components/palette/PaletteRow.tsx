import type { MouseEvent } from "react";
import { Icon } from "../shell/icons";
import type { PaletteItem } from "./paletteItems";

/** One option: kind icon | label + secondary | the CLI equivalent. The CLI
 *  is drawn from `data-cli` so it never doubles the row's text content. */
export default function PaletteRow({ item, index, active, onHover, onPick }: {
  item: PaletteItem;
  index: number;
  active: boolean;
  onHover: () => void;
  onPick: (e: MouseEvent) => void;
}) {
  return (
    <div
      role="option"
      id={`cmdk-opt-${index}`}
      aria-selected={active}
      aria-disabled={item.disabled || undefined}
      className={`cmdk-row${active ? " active" : ""}${item.disabled ? " disabled" : ""}`}
      data-cli={item.cli}
      onMouseMove={active ? undefined : onHover}
      onClick={onPick}
    >
      <span className="cmdk-icon"><Icon name={item.icon} /></span>
      <span className="cmdk-main" title={item.title ?? item.label}>
        {item.prefix && <span className="cmdk-ref mono">{item.prefix}</span>}
        <span className={`cmdk-label${item.mono ? " mono" : ""}`}>{item.label}</span>
        {item.secondary && <span className="cmdk-sub">{item.secondary}</span>}
      </span>
    </div>
  );
}
