/**
 * L1: FileTree (C4 file-upload §10.7 + honest-detection-results N8)
 *
 * 覆盖:空数据 / 扁平归档 / 嵌套(按 source_archive 分组)三种渲染。
 * honest-detection-results N8:归档行默认折叠,展开后显示子文件。
 */
import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import FileTree from "./FileTree";
import type { BidDocument } from "../../types";

function makeDoc(overrides: Partial<BidDocument>): BidDocument {
  return {
    id: 1,
    bidder_id: 1,
    file_name: "x.docx",
    file_path: "x.docx",
    file_size: 1,
    file_type: ".docx",
    md5: "0".repeat(32),
    file_role: null,
    parse_status: "extracted",
    parse_error: null,
    source_archive: "main.zip",
    created_at: "2026-04-14T00:00:00Z",
    ...overrides,
  };
}

describe("FileTree", () => {
  it("空数据显示空态", () => {
    render(<FileTree documents={[]} />);
    expect(screen.getByTestId("filetree-empty")).toBeInTheDocument();
  });

  it("含归档行默认折叠,展开后看到子文件", () => {
    const docs: BidDocument[] = [
      makeDoc({
        id: 1,
        file_name: "main.zip",
        file_path: "/uploads/1/main.zip",
        file_type: ".zip",
        parse_status: "extracted",
      }),
      makeDoc({
        id: 2,
        file_name: "ok.docx",
        file_path: "ok.docx",
        file_type: ".docx",
        source_archive: "main.zip",
      }),
      makeDoc({
        id: 3,
        file_name: "sub.xlsx",
        file_path: "dir/sub.xlsx",
        file_type: ".xlsx",
        source_archive: "main.zip",
      }),
    ];
    render(<FileTree documents={docs} />);

    // Collapse header 可见,显示"原始压缩包 (1 个)"
    expect(screen.getByTestId("archives-collapse")).toBeInTheDocument();
    expect(screen.getByText(/原始压缩包/)).toBeInTheDocument();
    expect(screen.getByText(/1/)).toBeInTheDocument();

    // honest-detection-results N8:默认折叠状态下,归档行 + 子文件不可见
    expect(screen.queryByText("main.zip")).not.toBeInTheDocument();
    expect(screen.queryByText("ok.docx")).not.toBeInTheDocument();
    expect(screen.queryByText("sub.xlsx")).not.toBeInTheDocument();

    // 点击 Collapse header 展开
    const header = document.querySelector(".ant-collapse-header") as HTMLElement;
    fireEvent.click(header);

    // 展开后归档行 + 子文件可见
    expect(screen.getByText("main.zip")).toBeInTheDocument();
    expect(screen.getByText("ok.docx")).toBeInTheDocument();
    expect(screen.getByText("sub.xlsx")).toBeInTheDocument();
  });

  it("归档行 needs_password 展开后显示对应徽章", () => {
    const docs: BidDocument[] = [
      makeDoc({
        id: 5,
        file_name: "enc.7z",
        file_type: ".7z",
        parse_status: "needs_password",
        parse_error: "需要密码",
      }),
    ];
    render(<FileTree documents={docs} />);
    // 默认折叠,徽章先不可见
    expect(
      screen.queryByTestId("status-badge-needs_password"),
    ).not.toBeInTheDocument();
    // 展开
    const header = document.querySelector(".ant-collapse-header") as HTMLElement;
    fireEvent.click(header);
    expect(
      screen.getByTestId("status-badge-needs_password"),
    ).toBeInTheDocument();
  });

  // honest-detection-results N8: 无归档不渲染 Collapse(避免空入口)
  it("只有 docx 无 zip 归档时不渲染 Collapse 入口", () => {
    const docs: BidDocument[] = [
      makeDoc({
        id: 6,
        file_name: "lone.docx",
        file_type: ".docx",
        source_archive: "lone.docx",
      }),
    ];
    render(<FileTree documents={docs} />);
    expect(screen.queryByTestId("archives-collapse")).not.toBeInTheDocument();
    expect(screen.queryByText(/原始压缩包/)).not.toBeInTheDocument();
  });
});
