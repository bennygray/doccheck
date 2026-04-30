/**
 * L1: RerunAfterTenderDialog(detect-tender-baseline §7.16)
 *
 * 覆盖:渲染时显示 info Alert / 立即重跑 → onConfirm / 稍后 → onCancel / loading 禁取消
 */
import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import RerunAfterTenderDialog from "./RerunAfterTenderDialog";

describe("RerunAfterTenderDialog", () => {
  it("open=true 渲染 dialog", () => {
    render(
      <RerunAfterTenderDialog
        open
        onCancel={vi.fn()}
        onConfirm={vi.fn()}
      />,
    );
    expect(screen.getByTestId("rerun-after-tender-dialog")).toBeInTheDocument();
    expect(screen.getByTestId("rerun-confirm")).toHaveTextContent("立即重新检测");
  });

  it("open=false 不渲染 dialog 内容", () => {
    render(
      <RerunAfterTenderDialog
        open={false}
        onCancel={vi.fn()}
        onConfirm={vi.fn()}
      />,
    );
    expect(screen.queryByTestId("rerun-after-tender-dialog")).toBeNull();
  });

  it("点立即重跑 → onConfirm 触发", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    render(
      <RerunAfterTenderDialog
        open
        onCancel={vi.fn()}
        onConfirm={onConfirm}
      />,
    );
    await user.click(screen.getByTestId("rerun-confirm"));
    await waitFor(() => expect(onConfirm).toHaveBeenCalled());
  });

  it("点稍后 → onCancel 触发", async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();
    render(
      <RerunAfterTenderDialog
        open
        onCancel={onCancel}
        onConfirm={vi.fn()}
      />,
    );
    await user.click(screen.getByTestId("rerun-cancel"));
    await waitFor(() => expect(onCancel).toHaveBeenCalled());
  });

  it("loading=true 时取消按钮被禁用", () => {
    render(
      <RerunAfterTenderDialog
        open
        loading
        onCancel={vi.fn()}
        onConfirm={vi.fn()}
      />,
    );
    expect(screen.getByTestId("rerun-cancel")).toBeDisabled();
  });
});
