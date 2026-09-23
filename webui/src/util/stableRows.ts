/** The previous rows when a poll brought the same data, so memoized charts and
 *  anything keyed on the array's identity skip work that would change nothing. */
export function keepIfUnchanged<T>(prev: T[] | null, next: T[]): T[] {
  if (prev && prev.length === next.length && JSON.stringify(prev) === JSON.stringify(next)) {
    return prev;
  }
  return next;
}
