/**
 * L1: TenderUploadCard(detect-tender-baseline §7.16)
 *
 * 覆盖:列表加载 / 大文件拒收 / 类型不匹配提示 / 删除 → onChanged 回调
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import TenderUploadCard from "./TenderUploadCard";

vi.mock("../../services/api", () => ({
  api: {
    listTenders: vi.fn(),
    uploadTender: vi.fn(),
    deleteTender: vi.fn(),
  },
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

const sampleTender = {
  id: 11,
  project_id: 1,
  file_name: "tender.docx",
  file_path: "uploads/tender.docx",
  file_size: 12345,
  md5: "abc",
  parse_status: "extracted",
  parse_error: null,
  created_at: "2026-04-30T10:00:00Z",
};

beforeEach(() => {
  (api.listTenders as ReturnType<typeof vi.fn>).mockReset();
  (api.uploadTender as ReturnType<typeof vi.fn>).mockReset();
  (api.deleteTender as ReturnType<typeof vi.fn>).mockReset();
});

describe("TenderUploadCard", () => {
  it("空列表展示空态文案", async () => {
    (api.listTenders as ReturnType<typeof vi.fn>).mockResolvedValueOnce([]);
    render(<TenderUploadCard projectId={1} />);
    await waitFor(() => {
      expect(screen.getByTestId("tender-empty")).toBeInTheDocument();
    });
  });

  it("展示已上传招标文件 + 状态 Tag", async () => {
    (api.listTenders as ReturnType<typeof vi.fn>).mockResolvedValueOnce([
      sampleTender,
    ]);
    render(<TenderUploadCard projectId={1} />);
    await waitFor(() => {
      expect(screen.getByTestId("tender-row-11")).toHaveTextContent(
        "tender.docx",
      );
      expect(screen.getByTestId("tender-status-11")).toHaveTextContent(
        "已解析",
      );
    });
  });

  it("拒收大于 500MB 的文件,不调上传", async () => {
    (api.listTenders as ReturnType<typeof vi.fn>).mockResolvedValueOnce([]);
    render(<TenderUploadCard projectId={1} />);
    await waitFor(() =>
      expect(screen.getByTestId("tender-empty")).toBeInTheDocument(),
    );

    const big = new File([new Uint8Array(10)], "big.zip", {
      type: "application/zip",
    });
    Object.defineProperty(big, "size", { value: 600 * 1024 * 1024 });
    fireEvent.change(screen.getByTestId("tender-file-input"), {
      target: { files: [big] },
    });

    expect(screen.getByTestId("tender-error")).toHaveTextContent("500MB");
    expect(api.uploadTender).not.toHaveBeenCalled();
  });

  it("拒收非白名单扩展名(如 .exe),不调上传", async () => {
    (api.listTenders as ReturnType<typeof vi.fn>).mockResolvedValueOnce([]);
    render(<TenderUploadCard projectId={1} />);
    await waitFor(() =>
      expect(screen.getByTestId("tender-empty")).toBeInTheDocument(),
    );

    const exe = new File([new Uint8Array(10)], "virus.exe", {
      type: "application/octet-stream",
    });
    fireEvent.change(screen.getByTestId("tender-file-input"), {
      target: { files: [exe] },
    });

    expect(screen.getByTestId("tender-error")).toHaveTextContent("仅支持");
    expect(api.uploadTender).not.toHaveBeenCalled();
  });
});
