/** Server-Sent Events over fetch, for a bearer-token session (plan 23 W6):
 *  EventSource cannot send an Authorization header. The subset of the
 *  EventSource interface useLiveScope uses (onopen, onerror, named-event
 *  listeners, readyState, close), reconnecting with backoff like the
 *  browser's: the server's `retry:` (else 1 s), doubled per failure in a row
 *  up to 30 s. A refused stream (non-2xx) closes for good. */

const BASE_RETRY_MS = 1000;
const MAX_RETRY_MS = 30_000;

/** The `text/event-stream` format: fed decoded chunks, it calls *onEvent*
 *  per dispatched event and *onRetry* per valid `retry:` field. */
export class SseParser {
  private buffer = "";
  private type = "";
  private data: string[] = [];
  private lastWasCr = false;

  constructor(
    private onEvent: (type: string, data: string, id: string | null) => void,
    private onRetry: (ms: number) => void,
    private id: string | null = null,
  ) {}

  feed(chunk: string) {
    let text = chunk;
    // A \r\n split across chunks: the \n ends nothing new.
    if (this.lastWasCr && text.startsWith("\n")) text = text.slice(1);
    this.buffer += text;
    const lines = this.buffer.split(/\r\n|\r|\n/);
    this.buffer = lines.pop() ?? "";
    // "a\r" + "\nb": the trailing \r ended the line, its \n must not end another.
    this.lastWasCr = this.buffer === "" && text.endsWith("\r");
    for (const line of lines) this.line(line);
  }

  private line(line: string) {
    if (line === "") return this.dispatch();
    if (line.startsWith(":")) return;
    const at = line.indexOf(":");
    const field = at < 0 ? line : line.slice(0, at);
    let value = at < 0 ? "" : line.slice(at + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") this.type = value;
    else if (field === "data") this.data.push(value);
    else if (field === "id" && !value.includes("\0")) this.id = value;
    else if (field === "retry" && /^\d+$/.test(value)) this.onRetry(Number(value));
  }

  private dispatch() {
    const { type, data } = this;
    this.type = "";
    this.data = [];
    if (data.length) this.onEvent(type || "message", data.join("\n"), this.id);
  }
}

type Listener = (e: MessageEvent) => void;

export class FetchEventSource {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSED = 2;
  readyState = FetchEventSource.CONNECTING;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  private listeners = new Map<string, Listener[]>();
  private abort: AbortController | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private retryMs = BASE_RETRY_MS;
  private failures = 0;
  private lastId: string | null = null;

  constructor(public url: string, private headers: Record<string, string>) {
    void this.connect();
  }

  addEventListener(type: string, fn: Listener) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), fn]);
  }

  close() {
    this.readyState = FetchEventSource.CLOSED;
    this.abort?.abort();
    if (this.timer !== null) clearTimeout(this.timer);
    this.timer = null;
  }

  private async connect() {
    const abort = new AbortController();
    this.abort = abort;
    const headers: Record<string, string> = { ...this.headers, Accept: "text/event-stream" };
    if (this.lastId !== null) headers["Last-Event-ID"] = this.lastId;
    try {
      const res = await fetch(this.url, { headers, signal: abort.signal, cache: "no-store" });
      if (this.closed()) return;
      if (!res.ok || !res.body) return this.refused();
      this.readyState = FetchEventSource.OPEN;
      this.failures = 0;
      this.onopen?.();
      await this.read(res.body);
    } catch {
      // A network error or the abort of close(): dropped below unless closed.
    }
    if (!this.closed()) this.dropped();
  }

  private async read(body: ReadableStream<Uint8Array>) {
    const reader = body.getReader();
    const decoder = new TextDecoder();
    const parser = new SseParser(
      (type, data, id) => this.emit(type, data, id),
      (ms) => { this.retryMs = ms; },
      this.lastId,
    );
    for (;;) {
      const { done, value } = await reader.read();
      if (done || this.closed()) return;
      parser.feed(decoder.decode(value, { stream: true }));
    }
  }

  private emit(type: string, data: string, id: string | null) {
    this.lastId = id;
    if (this.closed()) return;
    const event = new MessageEvent(type, { data, lastEventId: id ?? "" });
    for (const fn of this.listeners.get(type) ?? []) fn(event);
  }

  private closed() {
    return this.readyState === FetchEventSource.CLOSED;
  }

  private refused() {
    this.close();
    this.onerror?.();
  }

  private dropped() {
    this.readyState = FetchEventSource.CONNECTING;
    const delay = Math.min(MAX_RETRY_MS, this.retryMs * 2 ** this.failures);
    this.failures += 1;
    this.onerror?.();
    if (this.closed()) return; // closed by onerror
    this.timer = setTimeout(() => {
      this.timer = null;
      void this.connect();
    }, delay);
  }
}
