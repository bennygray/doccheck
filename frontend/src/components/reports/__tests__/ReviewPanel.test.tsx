import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ReviewPanel from "../ReviewPanel";
import { api } from "../../../services/api";

describe("ReviewPanel", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("未复核状态显示表单 + 提交校验 status 必填", async () => {
    const spy = vi.spyOn(api, "postReview");
    render(
      <ReviewPanel
        projectId={1}
        version={1}
        current={{
          status: null,
          comment: null,
          reviewer_id: null,
          reviewed_at: null,
        }}
      />,
    );
    // 直接提交(status 未选)
    fireEvent.click(screen.getByRole("button", { name: /提交复核/ }));
    await waitFor(() => {
      expect(screen.getByText(/请选择复核结论/)).toBeInTheDocument();
    });
    expect(spy).not.toHaveBeenCalled();
  });

  it("合法提交调用 API + 触发 onSubmitted", async () => {
    const onSubmitted = vi.fn();
    vi.spyOn(api, "postReview").mockResolvedValue({
      manual_review_status: "confirmed",
      manual_review_comment: "证据充分",
      reviewer_id: 3,
      reviewed_at: new Date().toISOString(),
    });
    render(
      <ReviewPanel
        projectId={1}
        version={1}
        current={{
          status: null,
          comment: null,
          reviewer_id: null,
          reviewed_at: null,
        }}
        onSubmitted={onSubmitted}
      />,
    );
    fireEvent.change(screen.getByRole("combobox"), {
      target: { value: "confirmed" },
    });
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "证据充分" },
    });
    fireEvent.click(screen.getByRole("button", { name: /提交复核/ }));
    await waitFor(() => expect(onSubmitted).toHaveBeenCalled());
    expect(api.postReview).toHaveBeenCalledWith(1, 1, {
      status: "confirmed",
      comment: "证据充分",
    });
  });

  it("已复核状态显示只读摘要 + 可修改", async () => {
    render(
      <ReviewPanel
        projectId={1}
        version={1}
        current={{
          status: "downgraded",
          comment: "重新评估",
          reviewer_id: 5,
          reviewed_at: "2026-04-16T10:00:00Z",
        }}
      />,
    );
    expect(screen.getByText(/降级风险/)).toBeInTheDocument();
    expect(screen.getByText(/重新评估/)).toBeInTheDocument();
    // 修改按钮存在
    fireEvent.click(screen.getByRole("button", { name: /修改/ }));
    // 进入编辑态 → textarea 可见
    await waitFor(() => {
      expect(screen.getByRole("textbox")).toBeInTheDocument();
    });
  });
});
