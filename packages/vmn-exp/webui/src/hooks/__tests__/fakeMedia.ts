/** A window.matchMedia for jsdom: the queries listed match, the rest don't,
 *  and `set` flips one and tells its listeners. */
type Listener = (e: MediaQueryListEvent) => void;

export function fakeMedia(matching: readonly string[]) {
  const on = new Set(matching);
  const listeners = new Map<string, Set<Listener>>();
  const of = (q: string) => listeners.get(q) ?? listeners.set(q, new Set()).get(q)!;
  window.matchMedia = ((query: string) => ({
    get matches() { return on.has(query); },
    media: query,
    onchange: null,
    addEventListener: (_: string, l: Listener) => of(query).add(l),
    removeEventListener: (_: string, l: Listener) => of(query).delete(l),
    addListener: (l: Listener) => of(query).add(l),
    removeListener: (l: Listener) => of(query).delete(l),
    dispatchEvent: () => true,
  })) as unknown as typeof window.matchMedia;
  return {
    set(query: string, value: boolean) {
      if (value) on.add(query); else on.delete(query);
      of(query).forEach((l) => l({ matches: value, media: query } as MediaQueryListEvent));
    },
  };
}

export function dropFakeMedia() {
  delete (window as { matchMedia?: unknown }).matchMedia;
}
