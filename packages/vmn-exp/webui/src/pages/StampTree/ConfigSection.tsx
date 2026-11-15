import { useEffect, useState } from "react";
import { api } from "../../api";
import type { AppConfig } from "../../types";
import { Disclosure } from "./Disclosure";

/** One conf.yml line, split into comment / key / value spans. */
function YamlLine({ line }: { line: string }) {
  const comment = line.match(/^(\s*)#(.*)$/);
  if (comment) {
    return <span className="yaml-comment">{line}</span>;
  }
  const kv = line.match(/^(\s*(?:- )?)([^:#]+):(\s?)(.*)$/);
  if (kv) {
    const [, indent, key, sep, rest] = kv;
    return (
      <>
        {indent}
        <span className="yaml-key">{key}</span>:{sep}
        {rest && <span className="yaml-value">{rest}</span>}
      </>
    );
  }
  return <span className="yaml-value">{line}</span>;
}

/** The raw conf.yml, syntax-highlighted. */
function YamlBlock({ text }: { text: string }) {
  return (
    <pre className="yaml-block">
      {text.replace(/\n$/, "").split("\n").map((line, i) => (
        <div key={i}>{line ? <YamlLine line={line} /> : " "}</div>
      ))}
    </pre>
  );
}

/** The app's conf.yml as recorded at the selected version's tag. */
export function ConfigSection({ ws, app, verstr }: { ws: string; app: string; verstr: string }) {
  const [open, setOpen] = useState(false);
  const [cfg, setCfg] = useState<AppConfig | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let live = true;
    setCfg(null);
    setError(null);
    api.config(ws, app, verstr)
      .then((c) => live && setCfg(c))
      .catch((e) => live && setError(String(e)));
    return () => { live = false; };
  }, [open, ws, app, verstr]);

  return (
    <div style={{ marginTop: 16 }}>
      <Disclosure open={open} onToggle={() => setOpen((o) => !o)} label="config" />
      {open && (
        <div style={{ marginTop: 8 }}>
          {error && <div className="error">{error}</div>}
          {cfg && (cfg.text ? (
            <YamlBlock text={cfg.text} />
          ) : (
            <div style={{ color: "var(--text-muted)" }}>
              no conf.yml at this version (defaults)
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
