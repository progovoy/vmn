import "@testing-library/jest-dom/vitest";

// Newer Node ships its own `localStorage` global (unusable without
// --localstorage-file) which shadows jsdom's: give tests a working one.
if (typeof globalThis.localStorage?.clear !== "function") {
  const store = new Map<string, string>();
  const memory: Storage = {
    get length() { return store.size; },
    clear: () => store.clear(),
    getItem: (k) => store.get(k) ?? null,
    key: (i) => [...store.keys()][i] ?? null,
    removeItem: (k) => { store.delete(k); },
    setItem: (k, v) => { store.set(k, String(v)); },
  };
  Object.defineProperty(globalThis, "localStorage", { value: memory, configurable: true });
}

// jsdom has no ResizeObserver; charts and the stamp tree observe their size.
// A test that drives resize callbacks installs its own stub over this one.
globalThis.ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
} as unknown as typeof ResizeObserver;
