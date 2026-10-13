/** A stand-in for the browser's EventSource: tests drive open/error/events.
 *  Install it with `vi.stubGlobal("EventSource", FakeSource)`. */
export class FakeSource {
  static instances: FakeSource[] = [];
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSED = 2;
  readyState = FakeSource.CONNECTING;
  closed = false;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  listeners = new Map<string, ((e: MessageEvent) => void)[]>();
  constructor(public url: string) { FakeSource.instances.push(this); }
  addEventListener(kind: string, fn: (e: MessageEvent) => void) {
    this.listeners.set(kind, [...(this.listeners.get(kind) ?? []), fn]);
  }
  close() { this.closed = true; this.readyState = FakeSource.CLOSED; }
  open() { this.readyState = FakeSource.OPEN; this.onopen?.(); }
  fail(closed = false) { this.readyState = closed ? FakeSource.CLOSED : FakeSource.CONNECTING; this.onerror?.(); }
  emit(kind: string, data: unknown) {
    for (const fn of this.listeners.get(kind) ?? []) fn(new MessageEvent(kind, { data: JSON.stringify(data) }));
  }
}

export const lastSource = () => FakeSource.instances[FakeSource.instances.length - 1];
