/**
 * L1: AddBidderDialog (C4 file-upload §10.6)
 *
 * 覆盖:空 name 拒提交 / 大文件拒收 / 类型不匹配提示。
 */
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import AddBidderDialog from "./AddBidderDialog";

vi.mock("../../services/api", () => ({
  api: { createBidder: vi.fn() },
  ApiError: class ApiError extends Error {
    status: number;
    detail: unknown;
    constructor(status: number, detail: unknown) {
      super(`API error ${status}`);
      this.status = status;
      this.detail = detail;
    }
  },
}));

import { api } from "../../services/api";

function renderDialog() {
  const onClose = vi.fn();
  const onCreated = vi.fn();
  render(
    <AddBidderDialog projectId={1} onClose={onClose} onCreated={onCreated} />,
  );
  return { onClose, onCreated };
}

describe("AddBidderDialog", () => {
  it("空 name 提交时显示错误,不调 API", async () => {
    const user = userEvent.setup();
    const { onCreated } = renderDialog();

    await user.click(screen.getByTestId("bidder-submit"));

    expect(screen.getByTestId("bidder-form-error")).toHaveTextContent(
      "投标人名称不能为空",
    );
    expect(api.createBidder).not.toHaveBeenCalled();
    expect(onCreated).not.toHaveBeenCalled();
  });

  it("成功提交触发 onCreated", async () => {
    const user = userEvent.setup();
    (api.createBidder as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      id: 7,
      name: "A",
      project_id: 1,
      parse_status: "pending",
      parse_error: null,
      file_count: 0,
      identity_info: null,
      created_at: "2026-04-14T00:00:00Z",
      updated_at: "2026-04-14T00:00:00Z",
    });
    const { onCreated } = renderDialog();
    await user.type(screen.getByTestId("bidder-name-input"), "A 公司");
    await user.click(screen.getByTestId("bidder-submit"));

    await waitFor(() => expect(onCreated).toHaveBeenCalled());
    expect(api.createBidder).toHaveBeenCalledWith(1, "A 公司", null);
  });

  it("大文件被拒并显示错误", async () => {
    const user = userEvent.setup();
    renderDialog();

    const big = new File(
      [new Uint8Array(10)],
      "huge.zip",
      { type: "application/zip" },
    );
    Object.defineProperty(big, "size", { value: 600 * 1024 * 1024 });
    await user.upload(screen.getByTestId("bidder-file-input"), big);

    expect(screen.getByTestId("bidder-form-error")).toHaveTextContent("500MB");
  });

  it("不支持的扩展名被拒", async () => {
    renderDialog();
    const exe = new File([new Uint8Array(10)], "virus.exe", {
      type: "application/octet-stream",
    });
    // user.upload 受 input accept 属性限制,这里直接 fireEvent 触发 onChange
    fireEvent.change(screen.getByTestId("bidder-file-input"), {
      target: { files: [exe] },
    });
    expect(screen.getByTestId("bidder-form-error")).toHaveTextContent(
      ".zip / .7z / .rar",
    );
  });
});
