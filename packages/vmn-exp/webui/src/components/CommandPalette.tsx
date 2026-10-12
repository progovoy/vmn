import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useApps } from "../queries";
import { useDebounce } from "../hooks/useDebounce";
import { useFocusTrap } from "../hooks/useFocusTrap";
import type { ShellContext } from "../shell/contracts";
import { copyText } from "../util";
import { Icon } from "./shell/icons";
import PaletteRow from "./palette/PaletteRow";
import { buildSections, capItems, type PaletteItem } from "./palette/paletteItems";
import { completeCli, parseCliQuery, type CliIntent } from "./palette/parseCliQuery";
import { readRecents } from "./palette/recents";
import { usePaletteCatalog, usePaletteRuns } from "./palette/usePaletteRuns";
import { useRefResolution } from "./palette/useRefResolution";
import "./palette/palette.css";

const PLACEHOLDER = "Jump to @54, show -v <ref>, compare @3 @7, goto <version>, app or page…";
const KEYS = "↑↓ move · ↵ open · ⌘↵ new tab · ⇧↵ copy CLI · tab complete · esc close";

interface Entry { item: PaletteItem; section: string; index: number; more?: boolean }

const refsOf = (intent: CliIntent) =>
  intent.kind === "show" ? [intent.ref] : intent.kind === "compare" || intent.kind === "overlay" ? intent.refs : [];
const appOf = (intent: CliIntent) => ("app" in intent ? intent.app : undefined);

/** The section starts before and after *i*, for PageUp / PageDown. */
function sectionJump(flat: Entry[], i: number, dir: 1 | -1): number {
  const starts = flat.flatMap((e, j) => (j === 0 || flat[j - 1].section !== e.section ? [j] : []));
  if (dir === 1) return starts.find((s) => s > i) ?? i;
  const own = starts.filter((s) => s <= i).pop() ?? 0;
  return starts.filter((s) => s < own).pop() ?? 0;
}

export default function CommandPalette({ ctx, onClose }: { ctx: ShellContext; onClose: () => void }) {
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const [expanded, setExpanded] = useState<string[]>([]);
  const [copied, setCopied] = useState<string | null>(null);
  const [recents] = useState(readRecents);
  const dialogRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();
  useFocusTrap(dialogRef, { initialFocus: inputRef });

  const apps = useApps(ctx.ws).data;
  const appNames = useMemo(() => (apps ?? []).map((a) => a.name), [apps]);
  const intent = useMemo(
    () => parseCliQuery(q, { apps: appNames, workspaces: ctx.workspaces.map((w) => w.name), app: ctx.app }),
    [q, appNames, ctx.workspaces, ctx.app],
  );
  const text = q.trim();
  const { runs, searched } = usePaletteRuns(ctx.ws, ctx.app, intent.kind === "none" ? text : "");
  const refs = useRefResolution(ctx.ws, appOf(intent), refsOf(intent));
  const { models, reports } = usePaletteCatalog(ctx.ws, text.length >= 2);

  const sections = buildSections({
    ctx, text, intent, refs, runs, searched, apps: apps ?? [], models, reports, recents,
  });
  let index = 0;
  const groups = sections.map((s) => {
    const { items, more } = capItems(s, expanded.includes(s.key));
    const entries: Entry[] = items.map((item) => ({ item, section: s.key, index: index++ }));
    if (more) {
      const item = { id: `more:${s.key}`, icon: "chevron-down" as const, label: `${more} more` };
      entries.push({ item, section: s.key, index: index++, more: true });
    }
    if (s.tail) entries.push({ item: s.tail, section: s.key, index: index++ });
    return { section: s, entries };
  });
  const flat = groups.flatMap((g) => g.entries);
  const current = Math.min(active, flat.length - 1);
  const announce = useDebounce(`${flat.length} ${flat.length === 1 ? "result" : "results"}`, 300);

  useEffect(() => { setActive(0); setCopied(null); }, [q]);
  useEffect(() => {
    document.getElementById(`cmdk-opt-${current}`)?.scrollIntoView?.({ block: "nearest" });
  }, [current]);

  const copy = (command: string) =>
    copyText(command).then((ok) => setCopied(ok ? `Copied ${command}` : "Copy failed"));

  const activate = (i: number, mods: { newTab?: boolean; copy?: boolean } = {}) => {
    const entry = flat[i];
    if (!entry) return;
    const { item } = entry;
    if (entry.more) return setExpanded((keys) => [...keys, entry.section]);
    if (item.disabled) return;
    if (mods.copy || item.copyOnEnter) return void (item.command && copy(item.command));
    if (item.fill) {
      setQ(item.fill);
      return inputRef.current?.focus();
    }
    if (!item.to) return;
    if (mods.newTab || item.external) {
      window.open(item.to, "_blank", "noopener");
      if (!mods.newTab) onClose();
      return;
    }
    navigate(item.to, { state: { focusMain: true } });
    onClose();
  };

  // On the dialog, not the document: keys only mean something while it has focus.
  const onKeyDown = (e: KeyboardEvent) => {
    const n = flat.length;
    const move = (i: number) => {
      e.preventDefault();
      if (n) setActive(i);
    };
    switch (e.key) {
      case "ArrowDown": return move((current + 1) % n);
      case "ArrowUp": return move((current - 1 + n) % n);
      case "Home": return move(0);
      case "End": return move(n - 1);
      case "PageDown": return move(sectionJump(flat, current, 1));
      case "PageUp": return move(sectionJump(flat, current, -1));
      case "Enter":
        e.preventDefault();
        return activate(current, { newTab: e.metaKey || e.ctrlKey, copy: e.shiftKey });
      case "Tab": {
        // The focus trap keeps focus inside whether or not this completes.
        const done = e.shiftKey ? null : completeCli(q, appNames);
        if (done) {
          e.preventDefault();
          setQ(done);
        }
        return;
      }
      case "Escape":
        e.preventDefault();
        e.stopPropagation();
        return q ? setQ("") : onClose();
    }
  };

  return (
    <div className="cmdk-veil" onMouseDown={onClose}>
      <div
        ref={dialogRef}
        className="cmdk"
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        onMouseDown={(e) => e.stopPropagation()}
        onKeyDown={onKeyDown}
      >
        <div className="cmdk-field">
          <Icon name="search" />
          <input
            ref={inputRef}
            role="combobox"
            aria-label="Command"
            aria-expanded="true"
            aria-controls="cmdk-list"
            aria-autocomplete="list"
            aria-activedescendant={flat.length ? `cmdk-opt-${current}` : undefined}
            aria-describedby="cmdk-keys"
            placeholder={PLACEHOLDER}
            spellCheck={false}
            autoComplete="off"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>
        <div className="cmdk-list" role="listbox" id="cmdk-list" aria-label="Results">
          {groups.map(({ section, entries }) => (
            <div key={section.key} role="group" aria-labelledby={`cmdk-sec-${section.key}`}>
              <div className="cmdk-sec" id={`cmdk-sec-${section.key}`}>{section.title}</div>
              {entries.map(({ item, index: i }) => (
                <PaletteRow
                  key={item.id}
                  item={item}
                  index={i}
                  active={i === current}
                  onHover={() => setActive(i)}
                  onPick={(e) => activate(i, { newTab: e.metaKey || e.ctrlKey, copy: e.shiftKey })}
                />
              ))}
            </div>
          ))}
        </div>
        {text && !flat.length && (
          <p className="cmdk-empty">
            No match for "{text}". Try @12, show -v &lt;verstr&gt;, compare @3 @7, or metrics.loss &lt; 0.3.
          </p>
        )}
        <div className="cmdk-foot" aria-hidden="true">{KEYS}</div>
        <span id="cmdk-keys" className="cmdk-sr">{KEYS}</span>
        <div role="status" aria-live="polite" className="cmdk-sr">{copied ?? announce}</div>
      </div>
    </div>
  );
}
