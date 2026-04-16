import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ExportButton from "../ExportButton";
import { ApiError, api } from "../../../services/api";

class MockEventSource {
  listeners: Record<string, (e: MessageEvent) => void> = {};
  constructor(public url: string) {
    (MockEventSource as unknown as { last: MockEventSource }).last = this;
  }
  addEventListener(type: string, cb: (e: MessageEvent) => void) {
    this.listeners[type] = cb;
  }
  dispatch(type: string, data: object) {
    this.listeners[type]?.(new MessageEvent(type, { data: JSON.stringify(data) }));
  }
  close() {}
  onerror: ((e: Event) => void) | null = null;
}

describe("ExportButton", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    // @ts-expect-error - override for test
    globalThis.EventSource = MockEventSource;
    // 避免 window.open 真的打开
    vi.spyOn(window, "open").mockImplementation(() => null);
  });

  it("idle → 点击触发 API + 进入 running", async () => {
    vi.spyOn(api, "startExport").mockResolvedValue({ job_id: 42 });
    render(<ExportButton projectId={1} version={1} />);
    expect(screen.getByRole("button", { name: /导出 Word/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /导出 Word/ }));
    await waitFor(() => {
      expect(api.startExport).toHaveBeenCalled();
    });
  });

  it("SSE export_progress phase=done → 切 done 态 + 下载链接可见", async () => {
    vi.spyOn(api, "startExport").mockResolvedValue({ job_id: 7 });
    render(<ExportButton projectId={1} version={1} />);
    fireEvent.click(screen.getByRole("button", { name: /导出 Word/ }));
    await waitFor(() => expect(api.startExport).toHaveBeenCalled());
    // 取到 mock SSE 实例
    const es = (MockEventSource as unknown as { last: MockEventSource }).last;
    es.dispatch("export_progress", {
      job_id: 7,
      phase: "done",
      progress: 1,
      message: "",
    });
    await waitFor(() => {
      expect(screen.getByText(/已生成/)).toBeInTheDocument();
    });
  });

  it("API 启动失败 → failed 态 + 重试按钮", async () => {
    vi.spyOn(api, "startExport").mockRejectedValue(new ApiError(500, "boom"));
    render(<ExportButton projectId={1} version={1} />);
    fireEvent.click(screen.getByRole("button", { name: /导出 Word/ }));
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /重试/ })).toBeInTheDocument();
    });
  });

  it("SSE phase=failed → failed 态", async () => {
    vi.spyOn(api, "startExport").mockResolvedValue({ job_id: 9 });
    render(<ExportButton projectId={1} version={1} />);
    fireEvent.click(screen.getByRole("button", { name: /导出 Word/ }));
    await waitFor(() => expect(api.startExport).toHaveBeenCalled());
    const es = (MockEventSource as unknown as { last: MockEventSource }).last;
    es.dispatch("export_progress", {
      job_id: 9,
      phase: "failed",
      progress: 1,
      message: "render error",
    });
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /重试/ })).toBeInTheDocument();
    });
  });
});
