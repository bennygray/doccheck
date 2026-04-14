/**
 * L1 前端:useParseProgress hook (C5 §10.4)
 *
 * 测试:
 * - 连接成功收 snapshot 更新 bidders/progress
 * - 收 bidder_status_changed 更新对应 bidder 状态
 * - onerror 切换到 connected=false(降级轮询)
 */
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useParseProgress } from "./useParseProgress";

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
  emit(type: string, data: unknown) {
    const msg = new MessageEvent(type, { data: JSON.stringify(data) });
    for (const l of this.listeners.get(type) ?? []) l(msg);
  }
  fail() {
    this.onerror?.(new Event("error"));
  }
}

let created: MockEventSource[] = [];

vi.mock("../services/api", () => ({
  api: {
    getProject: vi.fn().mockResolvedValue({
      bidders: [],
      progress: null,
    }),
    parseProgressUrl: (pid: number | string) =>
      `/api/projects/${pid}/parse-progress`,
  },
}));
vi.mock("../contexts/AuthContext", () => ({
  authStorage: {
    getToken: () => "tok",
    setPendingPath: () => {},
  },
}));

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

describe("useParseProgress", () => {
  it("初始 connected=false,open 后 connected=true", async () => {
    const { result } = renderHook(() => useParseProgress(1));
    expect(result.current.connected).toBe(false);
    await waitFor(() => expect(result.current.connected).toBe(true));
  });

  it("snapshot 事件填充 bidders/progress", async () => {
    const { result } = renderHook(() => useParseProgress(1));
    await waitFor(() => expect(result.current.connected).toBe(true));

    act(() => {
      created[0].emit("snapshot", {
        bidders: [{ id: 1, name: "B1", parse_status: "extracted", file_count: 3 }],
        progress: {
          total_bidders: 1,
          pending_count: 0,
          extracting_count: 0,
          extracted_count: 1,
          identifying_count: 0,
          identified_count: 0,
          pricing_count: 0,
          priced_count: 0,
          partial_count: 0,
          failed_count: 0,
          needs_password_count: 0,
        },
      });
    });

    await waitFor(() => expect(result.current.bidders).toHaveLength(1));
    expect(result.current.progress?.total_bidders).toBe(1);
  });

  it("bidder_status_changed 更新对应 bidder 状态", async () => {
    const { result } = renderHook(() => useParseProgress(1));
    await waitFor(() => expect(result.current.connected).toBe(true));

    act(() => {
      created[0].emit("snapshot", {
        bidders: [
          { id: 1, name: "B1", parse_status: "extracted", file_count: 2 },
        ],
        progress: null,
      });
    });
    await waitFor(() =>
      expect(result.current.bidders[0]?.parse_status).toBe("extracted"),
    );

    act(() => {
      created[0].emit("bidder_status_changed", {
        bidder_id: 1,
        new_status: "identified",
      });
    });

    await waitFor(() =>
      expect(result.current.bidders[0]?.parse_status).toBe("identified"),
    );
  });

  it("onerror 触发 connected=false", async () => {
    const { result } = renderHook(() => useParseProgress(1));
    await waitFor(() => expect(result.current.connected).toBe(true));

    act(() => {
      created[0].fail();
    });

    await waitFor(() => expect(result.current.connected).toBe(false));
  });
});
