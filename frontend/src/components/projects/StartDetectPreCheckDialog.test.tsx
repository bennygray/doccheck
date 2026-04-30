/**
 * L1: StartDetectPreCheckDialog(detect-tender-baseline §7.16)
 *
 * 覆盖:hasTender=false 显示警告 / 勾选"不再提醒"写入 localStorage / 取消不写
 * + shouldSkipPreCheckDialog 读 localStorage 工具函数
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import StartDetectPreCheckDialog, {
  dismissedStorageKey,
  shouldSkipPreCheckDialog,
} from "./StartDetectPreCheckDialog";

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  window.localStorage.clear();
});

describe("dismissedStorageKey", () => {
  it("按项目 id 派生 key", () => {
    expect(dismissedStorageKey(7)).toBe("tender_baseline_warning_dismissed_7");
  });
});

describe("shouldSkipPreCheckDialog", () => {
  it("默认 false", () => {
    expect(shouldSkipPreCheckDialog(7)).toBe(false);
  });
  it("写入 '1' 后 true", () => {
    window.localStorage.setItem(dismissedStorageKey(7), "1");
    expect(shouldSkipPreCheckDialog(7)).toBe(true);
  });
});

describe("StartDetectPreCheckDialog", () => {
  it("hasTender=false 渲染警告 Alert", () => {
    render(
      <StartDetectPreCheckDialog
        projectId={1}
        open
        hasTender={false}
        bidderCount={4}
        onCancel={vi.fn()}
        onConfirm={vi.fn()}
      />,
    );
    expect(screen.getByTestId("precheck-no-tender-alert")).toBeInTheDocument();
    expect(screen.getByTestId("precheck-no-tender-alert")).toHaveTextContent(
      "L2",
    );
  });

  it("hasTender=false + bidderCount<3 提示 L3 降级", () => {
    render(
      <StartDetectPreCheckDialog
        projectId={1}
        open
        hasTender={false}
        bidderCount={2}
        onCancel={vi.fn()}
        onConfirm={vi.fn()}
      />,
    );
    expect(screen.getByTestId("precheck-no-tender-alert")).toHaveTextContent(
      "L3",
    );
  });

  it("勾选'不再提醒'后确认,写入 localStorage", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    render(
      <StartDetectPreCheckDialog
        projectId={42}
        open
        hasTender={false}
        bidderCount={4}
        onCancel={vi.fn()}
        onConfirm={onConfirm}
      />,
    );
    await user.click(screen.getByTestId("precheck-dont-remind"));
    await user.click(screen.getByTestId("precheck-confirm"));
    await waitFor(() => expect(onConfirm).toHaveBeenCalled());
    expect(window.localStorage.getItem(dismissedStorageKey(42))).toBe("1");
  });

  it("未勾选'不再提醒'确认时不写 localStorage", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    render(
      <StartDetectPreCheckDialog
        projectId={42}
        open
        hasTender={false}
        bidderCount={4}
        onCancel={vi.fn()}
        onConfirm={onConfirm}
      />,
    );
    await user.click(screen.getByTestId("precheck-confirm"));
    await waitFor(() => expect(onConfirm).toHaveBeenCalled());
    expect(window.localStorage.getItem(dismissedStorageKey(42))).toBeNull();
  });

  it("hasTender=true 显示 info Alert(L1)", () => {
    render(
      <StartDetectPreCheckDialog
        projectId={1}
        open
        hasTender
        bidderCount={3}
        onCancel={vi.fn()}
        onConfirm={vi.fn()}
      />,
    );
    expect(screen.queryByTestId("precheck-no-tender-alert")).toBeNull();
  });
});
