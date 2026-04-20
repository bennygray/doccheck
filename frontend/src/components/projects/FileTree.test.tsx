/**
 * L1: FileTree (C4 file-upload §10.7)
 *
 * 覆盖:空数据 / 扁平归档 / 嵌套(按 source_archive 分组)三种渲染。
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
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

  it("含归档行 + 子文件按 source_archive 归组", () => {
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
    // 重设计后:图标用 antd Icon(FolderOpenOutlined/FileOutlined)替代 emoji;
    // 文件名以纯文本形式出现
    expect(screen.getByText("main.zip")).toBeInTheDocument();
    expect(screen.getByText("ok.docx")).toBeInTheDocument();
    expect(screen.getByText("sub.xlsx")).toBeInTheDocument();
  });

  it("归档行 needs_password 显示对应徽章", () => {
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
    expect(screen.getByTestId("status-badge-needs_password")).toBeInTheDocument();
  });
});
