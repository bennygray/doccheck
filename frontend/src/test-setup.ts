import "@testing-library/jest-dom/vitest";

// @ant-design/charts 依赖 canvas,jsdom 不支持 → 测试里返占位 div
import { vi } from "vitest";
vi.mock("@ant-design/charts", () => {
  const React = require("react");
  const stub = (props: { data?: unknown }) =>
    React.createElement("div", {
      "data-testid": "chart-stub",
      "data-chart-items": Array.isArray(props.data) ? props.data.length : 0,
    });
  return {
    Radar: stub,
    Column: stub,
    Bar: stub,
    Pie: stub,
    Line: stub,
    Gauge: stub,
    Area: stub,
  };
});

// antd v5 的 Grid / ResponsiveObserver 依赖 window.matchMedia,jsdom 不实现 → 补 polyfill
if (typeof window !== "undefined" && typeof window.matchMedia !== "function") {
  window.matchMedia = (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }) as unknown as MediaQueryList;
}

// antd 部分组件依赖 ResizeObserver,jsdom 也不实现
if (typeof window !== "undefined" && typeof window.ResizeObserver === "undefined") {
  window.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as typeof ResizeObserver;
}

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
