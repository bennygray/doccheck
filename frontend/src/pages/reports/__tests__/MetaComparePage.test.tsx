import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import MetaComparePage from "../MetaComparePage";
import { api } from "../../../services/api";
import type { MetaCompareResponse } from "../../../types";

const renderAt = (path: string) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route
          path="/reports/:projectId/:version/compare/metadata"
          element={<MetaComparePage />}
        />
      </Routes>
    </MemoryRouter>,
  );

const mkResp = (
  overrides: Partial<MetaCompareResponse> = {},
): MetaCompareResponse => ({
  bidders: [
    { bidder_id: 1, bidder_name: "甲公司" },
    { bidder_id: 2, bidder_name: "乙公司" },
  ],
  fields: [
    {
      field_name: "author",
      display_name: "作者",
      values: [
        { value: "张三", is_common: false, color_group: 0 },
        { value: "张三", is_common: false, color_group: 0 },
      ],
    },
    {
      field_name: "last_saved_by",
      display_name: "最后保存者",
      values: [
        { value: "Administrator", is_common: true, color_group: null },
        { value: "李四", is_common: false, color_group: 0 },
      ],
    },
    {
      field_name: "template",
      display_name: "文档模板",
      values: [
        { value: "Normal.dotm", is_common: false, color_group: 0 },
        { value: "Normal.dotm", is_common: false, color_group: 0 },
      ],
    },
  ],
  ...overrides,
});

describe("MetaComparePage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("渲染矩阵表格 + 字段行 + 投标人列", async () => {
    vi.spyOn(api, "getCompareMetadata").mockResolvedValue(mkResp());
    renderAt("/reports/1/1/compare/metadata");

    await waitFor(() => {
      expect(screen.getByText("甲公司")).toBeInTheDocument();
      expect(screen.getByText("作者")).toBeInTheDocument();
      expect(screen.getByText("文档模板")).toBeInTheDocument();
    });
  });

  it("通用值标灰 + tooltip", async () => {
    vi.spyOn(api, "getCompareMetadata").mockResolvedValue(mkResp());
    renderAt("/reports/1/1/compare/metadata");

    await waitFor(() => {
      const commonCells = screen.getAllByTestId("common-cell");
      expect(commonCells.length).toBeGreaterThan(0);
      expect(commonCells[0].getAttribute("title")).toBe("通用值,已过滤");
    });
  });

  it("匹配值着色(同 color_group 同背景色)", async () => {
    vi.spyOn(api, "getCompareMetadata").mockResolvedValue(mkResp());
    renderAt("/reports/1/1/compare/metadata");

    await waitFor(() => {
      const table = screen.getByTestId("meta-table");
      // author 行两个单元格都有 style.backgroundColor
      const authorRow = table.querySelectorAll("tbody tr")[0];
      const cells = authorRow.querySelectorAll("td");
      // cells[0] = 字段名, cells[1] = 甲, cells[2] = 乙
      const bgA = (cells[1] as HTMLElement).style.backgroundColor;
      const bgB = (cells[2] as HTMLElement).style.backgroundColor;
      expect(bgA).toBeTruthy();
      expect(bgA).toBe(bgB);
    });
  });
});
