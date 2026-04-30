import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { App as AntdApp } from "antd";

import { StartDetectButton } from "../StartDetectButton";
import { ApiError, api } from "../../../services/api";
import type { BidderSummary } from "../../../types";

/** 包一层 AntdApp 让组件内 App.useApp() 能拿到 message. */
function renderInApp(ui: React.ReactElement) {
  return render(<AntdApp>{ui}</AntdApp>);
}

const makeBidder = (
  overrides: Partial<BidderSummary> = {},
): BidderSummary => ({
  id: 1,
  name: "B",
  parse_status: "identified",
  file_count: 1,
  ...overrides,
});

describe("StartDetectButton", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    // detect-tender-baseline §7 / §8.0:.env flag=true 后 click 会先弹 precheck dialog,
    // 这里给所有测试默认 mock listTenders 返空 + localStorage 标 dismissed 跳过 dialog,
    // 避免对老测试断言"clicking button → startAnalysis 直调"的语义影响。
    vi.spyOn(api, "listTenders").mockResolvedValue([]);
    try {
      window.localStorage.setItem("tender_baseline_warning_dismissed_1", "1");
      window.localStorage.setItem("tender_baseline_warning_dismissed_42", "1");
    } catch {
      /* ignore */
    }
  });

  it("禁用当 bidder < 2", () => {
    renderInApp(
      <StartDetectButton
        projectId={1}
        projectStatus="ready"
        bidders={[makeBidder()]}
      />,
    );
    const btn = screen.getByRole("button");
    expect(btn).toBeDisabled();
    expect(btn).toHaveAttribute("title", expect.stringContaining("2个投标人"));
  });

  it("禁用当有非终态 bidder", () => {
    renderInApp(
      <StartDetectButton
        projectId={1}
        projectStatus="ready"
        bidders={[
          makeBidder(),
          makeBidder({ id: 2, parse_status: "identifying" }),
        ]}
      />,
    );
    const btn = screen.getByRole("button");
    expect(btn).toBeDisabled();
    expect(btn).toHaveAttribute(
      "title",
      expect.stringContaining("等待所有文件解析完成"),
    );
  });

  it("禁用当 analyzing", () => {
    renderInApp(
      <StartDetectButton
        projectId={1}
        projectStatus="analyzing"
        bidders={[makeBidder(), makeBidder({ id: 2 })]}
      />,
    );
    const btn = screen.getByRole("button");
    expect(btn).toBeDisabled();
    expect(btn).toHaveTextContent("检测进行中");
  });

  it("条件满足 → 可点 + 调 startAnalysis", async () => {
    const spy = vi
      .spyOn(api, "startAnalysis")
      .mockResolvedValue({ version: 1, agent_task_count: 10 });
    const onStarted = vi.fn();
    renderInApp(
      <StartDetectButton
        projectId={42}
        projectStatus="ready"
        bidders={[makeBidder(), makeBidder({ id: 2 })]}
        onStarted={onStarted}
      />,
    );
    const btn = screen.getByRole("button");
    expect(btn).not.toBeDisabled();
    fireEvent.click(btn);
    await waitFor(() => {
      expect(spy).toHaveBeenCalledWith(42);
      expect(onStarted).toHaveBeenCalledWith(1);
    });
  });

  it("409 → 提示已在检测中", async () => {
    vi.spyOn(api, "startAnalysis").mockRejectedValue(
      new ApiError(409, { current_version: 2 }),
    );
    renderInApp(
      <StartDetectButton
        projectId={1}
        projectStatus="ready"
        bidders={[makeBidder(), makeBidder({ id: 2 })]}
      />,
    );
    fireEvent.click(screen.getByRole("button"));
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("已在检测中");
    });
  });
});
