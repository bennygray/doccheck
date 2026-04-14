/**
 * L1 前端:useSSE hook — 事件派发后更新 history/latest
 *
 * 策略:在测试里注入一个可编程 EventSource mock,模拟后端推送 heartbeat。
 */

import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useSSE } from "./useSSE";

type Listener = (evt: MessageEvent) => void;

class MockEventSource {
  url: string;
  readyState = 0;
  onopen: ((ev: Event) => unknown) | null = null;
  onerror: ((ev: Event) => unknown) | null = null;
  onmessage: ((ev: MessageEvent) => unknown) | null = null;
  private listeners = new Map<string, Listener[]>();

  constructor(url: string) {
    this.url = url;
    // 异步打开,模拟真实行为
    setTimeout(() => {
      this.readyState = 1;
      this.onopen?.(new Event("open"));
    }, 0);
  }

  addEventListener(type: string, listener: Listener) {
    const arr = this.listeners.get(type) ?? [];
    arr.push(listener);
    this.listeners.set(type, arr);
  }

  removeEventListener() {}

  close() {
    this.readyState = 2;
  }

  /** 测试专用:从外部触发一个自定义 event */
  emit(type: string, data: unknown) {
    const msg = new MessageEvent(type, { data: JSON.stringify(data) });
    for (const l of this.listeners.get(type) ?? []) {
      l(msg);
    }
  }
}

let created: MockEventSource[] = [];

beforeEach(() => {
  created = [];
  (globalThis as { EventSource: unknown }).EventSource = class extends MockEventSource {
    constructor(url: string) {
      super(url);
      created.push(this);
    }
  };
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useSSE", () => {
  it("connecting → open → 接收 heartbeat 后 latest/history 更新", async () => {
    const { result } = renderHook(() => useSSE("/demo/sse", { events: ["heartbeat"] }));

    expect(result.current.status).toBe("connecting");
    expect(result.current.history).toHaveLength(0);

    // 等 onopen 异步回调
    await waitFor(() => expect(result.current.status).toBe("open"));

    // 派发一条 heartbeat
    act(() => {
      created[0].emit("heartbeat", { seq: 1, ts: "2026-04-14T00:00:00Z" });
    });

    await waitFor(() => expect(result.current.history).toHaveLength(1));
    expect(result.current.latest?.event).toBe("heartbeat");
    expect(result.current.latest?.data).toEqual({
      seq: 1,
      ts: "2026-04-14T00:00:00Z",
    });
  });
});
