/** Serializations of arrays already compared, so a poll serializes only the
 *  rows it just received, never the ones it is holding. */
const signatures = new WeakMap<object, string>();

function signatureOf(rows: readonly unknown[]): string {
  let sig = signatures.get(rows);
  if (sig === undefined) {
    sig = JSON.stringify(rows);
    signatures.set(rows, sig);
  }
  return sig;
}

/** The previous rows when a poll brought the same data, so memoized charts and
 *  anything keyed on the array's identity skip work that would change nothing. */
export function keepIfUnchanged<T>(prev: T[] | null, next: T[]): T[] {
  if (!prev || prev.length !== next.length) return next;
  const sig = JSON.stringify(next);
  if (signatureOf(prev) === sig) return prev;
  signatures.set(next, sig);
  return next;
}
