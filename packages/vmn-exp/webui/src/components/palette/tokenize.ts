/** Shell-style words for the palette's CLI grammar: whitespace splits,
 *  quotes group (and are dropped from `value`, kept in `raw`). */
export interface Token { value: string; raw: string; quoted: boolean }

export function tokenize(text: string): Token[] {
  const out: Token[] = [];
  let cur: Token | null = null;
  let quote: string | null = null;
  for (const ch of text) {
    if (quote) {
      if (ch === quote) quote = null;
      else cur!.value += ch;
      cur!.raw += ch;
    } else if (/\s/.test(ch)) {
      if (cur) out.push(cur);
      cur = null;
    } else {
      cur ??= { value: "", raw: "", quoted: false };
      cur.raw += ch;
      if (ch === "'" || ch === '"') {
        quote = ch;
        cur.quoted = true;
      } else cur.value += ch;
    }
  }
  if (cur) out.push(cur);
  return out;
}

/** Drop a pasted command's program words: `vmn-exp`/`vmn`, then `exp`/`experiment`. */
export function stripCliPrefix(tokens: Token[]): Token[] {
  let i = 0;
  if (["vmn-exp", "vmn"].includes(tokens[i]?.value)) i++;
  if (["exp", "experiment"].includes(tokens[i]?.value)) i++;
  return tokens.slice(i);
}

/** *arg* as one POSIX shell word. */
export function quoteArg(arg: string): string {
  if (/^[A-Za-z0-9@%_+=:,./-]+$/.test(arg)) return arg;
  return `'${arg.replaceAll("'", `'\\''`)}'`;
}

const commonPrefix = (words: string[]) =>
  words.reduce((acc, w) => {
    let i = 0;
    while (i < acc.length && acc[i] === w[i]) i++;
    return acc.slice(0, i);
  });

/** *text* with its last word completed from *candidates*: a unique match
 *  gets a trailing space, several extend to their common prefix; null when
 *  that adds nothing. */
export function completeToken(text: string, candidates: string[]): string | null {
  const word = text.match(/\S+$/)?.[0];
  if (!word) return null;
  const hits = candidates.filter((c) => c.startsWith(word) && c !== word);
  if (!hits.length) return null;
  const head = text.slice(0, text.length - word.length);
  if (hits.length === 1) return `${head}${hits[0]} `;
  const common = commonPrefix(hits);
  return common.length > word.length ? head + common : null;
}
