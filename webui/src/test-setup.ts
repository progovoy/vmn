import "@testing-library/jest-dom/vitest";

// Node >= 22 ships its own `localStorage` global (undefined unless node runs
// with --localstorage-file), which shadows jsdom's: hand jsdom's back.
const dom = (globalThis as { jsdom?: { window: Window } }).jsdom?.window;
if (dom && !globalThis.localStorage) {
  Object.defineProperty(globalThis, "localStorage", {
    value: dom.localStorage, configurable: true, writable: true,
  });
}
