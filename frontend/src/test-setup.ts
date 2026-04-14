import "@testing-library/jest-dom/vitest";

// 浏览器原生 EventSource 在 jsdom 里没有实现;useSSE 单测要么 mock,要么在
// 具体测试里按需替换全局。这里提供最小占位(立即 onerror 关闭),防止 import 时崩。
class NoopEventSource {
  url: string;
  readyState = 2;
  onopen: ((ev: Event) => unknown) | null = null;
  onerror: ((ev: Event) => unknown) | null = null;
  onmessage: ((ev: MessageEvent) => unknown) | null = null;
  constructor(url: string) {
    this.url = url;
  }
  addEventListener() {}
  removeEventListener() {}
  close() {}
}

// 只有 jsdom 里没定义时才注入,避免覆盖测试自己提供的 mock
if (typeof (globalThis as { EventSource?: unknown }).EventSource === "undefined") {
  (globalThis as { EventSource: unknown }).EventSource = NoopEventSource;
}
