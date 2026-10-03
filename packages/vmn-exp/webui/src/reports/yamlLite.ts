// A small YAML subset for vmn-panel blocks: block mappings and sequences,
// flow [a, b] / {k: v}, quoted and plain scalars, numbers, booleans, null and
// comments. Anything else (anchors, tags, block scalars, multi-line flow)
// throws a YamlLiteError naming the line.

export type YamlValue = string | number | boolean | null | YamlValue[] | { [k: string]: YamlValue };

export class YamlLiteError extends Error {}

interface Line {
  no: number;
  indent: number;
  text: string;
}

const NUMBER = /^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$/;
const UNSUPPORTED = /^[&*!|>%@`]/;
const DOUBLE_QUOTED = /^"(?:[^"\\]|\\.)*"/;
const SINGLE_QUOTED = /^'(?:[^']|'')*'/;
const quotedRe = (q: string) => (q === '"' ? DOUBLE_QUOTED : SINGLE_QUOTED);

function fail(no: number, message: string): never {
  throw new YamlLiteError(`line ${no}: ${message}`);
}

function stripComment(text: string): string {
  let quote = "";
  for (let i = 0; i < text.length; i += 1) {
    const c = text[i];
    if (quote) {
      if (c === "\\" && quote === '"') i += 1;
      else if (c === quote) quote = "";
    } else if (c === '"' || c === "'") quote = c;
    else if (c === "#" && (i === 0 || /\s/.test(text[i - 1]))) return text.slice(0, i);
  }
  return text;
}

function toLines(src: string): Line[] {
  const out: Line[] = [];
  src.replace(/\r\n?/g, "\n").split("\n").forEach((raw, k) => {
    const lead = raw.match(/^[ \t]*/)![0];
    if (lead.includes("\t") && raw.trim() !== "") fail(k + 1, "tabs are not allowed in indentation");
    const text = stripComment(raw).trimEnd();
    if (text.trim() !== "") out.push({ no: k + 1, indent: lead.length, text: text.trim() });
  });
  return out;
}

function plainScalar(s: string, no: number): YamlValue {
  if (s === "" || s === "~" || /^null$/i.test(s)) return null;
  if (/^true$/i.test(s)) return true;
  if (/^false$/i.test(s)) return false;
  if (NUMBER.test(s)) return Number(s);
  if (UNSUPPORTED.test(s)) fail(no, `unsupported syntax "${s[0]}"`);
  return s;
}

/** Recursive-descent parser for one line's flow value or scalar. */
class Flow {
  i = 0;
  constructor(private s: string, private no: number) {}

  parseAll(): YamlValue {
    const v = this.value("");
    this.ws();
    if (this.i < this.s.length) fail(this.no, `unexpected "${this.s.slice(this.i)}"`);
    return v;
  }

  private ws() {
    while (this.s[this.i] === " ") this.i += 1;
  }

  private value(stops: string): YamlValue {
    this.ws();
    const c = this.s[this.i];
    if (c === "[") return this.seq();
    if (c === "{") return this.map();
    if (c === '"' || c === "'") return this.quoted();
    return plainScalar(this.plain(stops), this.no);
  }

  private plain(stops: string): string {
    const start = this.i;
    while (this.i < this.s.length) {
      const c = this.s[this.i];
      if (stops.includes(c) && c !== ":") break;
      if (c === ":" && stops.includes(":") && /[\s,\]}]|^$/.test(this.s[this.i + 1] ?? "")) break;
      this.i += 1;
    }
    return this.s.slice(start, this.i).trim();
  }

  private quoted(): string {
    const q = this.s[this.i];
    const m = this.s.slice(this.i).match(quotedRe(q));
    if (!m) fail(this.no, `unterminated ${q === '"' ? "double" : "single"}-quoted string`);
    this.i += m[0].length;
    if (q === "'") return m[0].slice(1, -1).replace(/''/g, "'");
    try {
      return JSON.parse(m[0]) as string;
    } catch {
      fail(this.no, `unsupported escape in ${m[0]}`);
    }
  }

  private expect(c: string, what: string) {
    this.ws();
    if (this.s[this.i] !== c) fail(this.no, `expected "${c}" ${what}`);
    this.i += 1;
  }

  private items(close: string, item: () => void) {
    this.i += 1;
    this.ws();
    if (this.s[this.i] === close) {
      this.i += 1;
      return;
    }
    for (;;) {
      item();
      this.ws();
      if (this.s[this.i] === ",") this.i += 1;
      else return this.expect(close, `to close the flow collection (unclosed "${close === "]" ? "[" : "{"}")`);
    }
  }

  private seq(): YamlValue[] {
    const out: YamlValue[] = [];
    this.items("]", () => out.push(this.value(",]")));
    return out;
  }

  private map(): { [k: string]: YamlValue } {
    const out: { [k: string]: YamlValue } = {};
    this.items("}", () => {
      this.ws();
      const key = this.s[this.i] === '"' || this.s[this.i] === "'" ? this.quoted() : this.plain(",}:");
      this.expect(":", `after key "${key}"`);
      setKey(out, key, this.value(",}"), this.no);
    });
    return out;
  }
}

function setKey(map: { [k: string]: YamlValue }, key: string, value: YamlValue, no: number) {
  if (Object.prototype.hasOwnProperty.call(map, key)) fail(no, `duplicate key "${key}"`);
  map[key] = value;
}

/** Splits `key: rest` (colon followed by space or end of line); null if no key. */
function splitKey(text: string, no: number): [string, string] | null {
  if (text[0] === '"' || text[0] === "'") {
    const m = text.match(quotedRe(text[0]));
    const rest = m && text.slice(m[0].length).match(/^\s*:(?:\s+(.*))?$/);
    return m && rest ? [String(new Flow(m[0], no).parseAll()), rest[1] ?? ""] : null;
  }
  const m = text.match(/^([^\s[\]{},][^]*?)\s*:(?:\s+(.*))?$/);
  return m ? [m[1], m[2] ?? ""] : null;
}

class Block {
  i = 0;
  constructor(private lines: Line[]) {}

  parseDocument(): YamlValue {
    if (!this.lines.length) return null;
    const v = this.node(this.lines[0].indent);
    if (this.i < this.lines.length) fail(this.lines[this.i].no, "unexpected indentation or content");
    return v;
  }

  private node(indent: number): YamlValue {
    const line = this.lines[this.i];
    if (line.text === "-" || line.text.startsWith("- ")) return this.seq(indent);
    if (splitKey(line.text, line.no)) return this.map(indent);
    this.i += 1;
    return this.inline(line.text, line.no);
  }

  private inline(text: string, no: number): YamlValue {
    if (text === "|" || text === ">" || /^[|>][-+0-9]*$/.test(text)) fail(no, "unsupported block scalar");
    return new Flow(text, no).parseAll();
  }

  /** Value after `key:` or `-`: inline text, or the deeper block below. */
  private child(rest: string, no: number, indent: number, allowSameIndentSeq: boolean): YamlValue {
    if (rest !== "") return this.inline(rest, no);
    const next = this.lines[this.i];
    if (!next) return null;
    if (next.indent > indent) return this.node(next.indent);
    const seqHere = next.indent === indent && (next.text === "-" || next.text.startsWith("- "));
    return allowSameIndentSeq && seqHere ? this.seq(indent) : null;
  }

  private map(indent: number): { [k: string]: YamlValue } {
    const out: { [k: string]: YamlValue } = {};
    while (this.i < this.lines.length) {
      const line = this.lines[this.i];
      if (line.indent < indent) break;
      if (line.indent > indent) fail(line.no, "bad indentation");
      const kv = splitKey(line.text, line.no);
      if (!kv) fail(line.no, `expected "key: value", got "${line.text}"`);
      this.i += 1;
      setKey(out, kv[0], this.child(kv[1], line.no, indent, true), line.no);
    }
    return out;
  }

  private seq(indent: number): YamlValue[] {
    const out: YamlValue[] = [];
    while (this.i < this.lines.length) {
      const line = this.lines[this.i];
      if (line.indent < indent) break;
      if (line.indent > indent) fail(line.no, "bad indentation");
      if (!(line.text === "-" || line.text.startsWith("- "))) break;
      const rest = line.text.slice(1).trimStart();
      if (rest !== "" && splitKey(rest, line.no)) {
        // "- key: v" opens a mapping whose keys sit at the column after "- ".
        const col = indent + (line.text.length - rest.length);
        this.lines[this.i] = { no: line.no, indent: col, text: rest };
        out.push(this.map(col));
      } else {
        this.i += 1;
        out.push(this.child(rest, line.no, indent, false));
      }
    }
    return out;
  }
}

/** Parses the YAML subset described above; throws YamlLiteError otherwise. */
export function parseYamlLite(src: string): YamlValue {
  return new Block(toLines(src)).parseDocument();
}
