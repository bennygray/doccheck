import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import TextComparePage from "../TextComparePage";
import { api } from "../../../services/api";
import type { TextCompareResponse } from "../../../types";

const renderAt = (path: string) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route
          path="/reports/:projectId/:version/compare/text"
          element={<TextComparePage />}
        />
      </Routes>
    </MemoryRouter>,
  );

const mkResp = (
  overrides: Partial<TextCompareResponse> = {},
): TextCompareResponse => ({
  bidder_a_id: 1,
  bidder_b_id: 2,
  doc_role: "commercial",
  available_roles: ["commercial", "technical"],
  left_paragraphs: [
    { paragraph_index: 0, text: "甲公司段落0" },
    { paragraph_index: 1, text: "甲公司段落1" },
  ],
  right_paragraphs: [
    { paragraph_index: 0, text: "乙公司段落0" },
    { paragraph_index: 1, text: "乙公司段落1" },
  ],
  matches: [
    {
      a_idx: 0,
      b_idx: 0,
      sim: 0.92,
      label: "plagiarism",
      a_text: "甲公司段落0",
      b_text: "乙公司段落0",
    },
  ],
  has_more: false,
  total_count_left: 2,
  total_count_right: 2,
  ...overrides,
});

describe("TextComparePage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("渲染双栏段落 + 高亮", async () => {
    vi.spyOn(api, "getCompareText").mockResolvedValue(mkResp());
    renderAt("/reports/1/1/compare/text?bidder_a=1&bidder_b=2");

    await waitFor(() => {
      expect(screen.getByText("甲公司段落0")).toBeInTheDocument();
      expect(screen.getByText("乙公司段落0")).toBeInTheDocument();
    });

    // 匹配段落有 title 属性(相似度)
    const highlighted = screen.getByText("甲公司段落0");
    expect(highlighted.getAttribute("title")).toContain("92.0%");
  });

  it("角色切换下拉存在", async () => {
    vi.spyOn(api, "getCompareText").mockResolvedValue(mkResp());
    renderAt("/reports/1/1/compare/text?bidder_a=1&bidder_b=2");

    await waitFor(() => {
      const select = screen.getByRole("combobox");
      expect(select).toBeInTheDocument();
    });
  });

  it("无同角色文档 → 空状态", async () => {
    vi.spyOn(api, "getCompareText").mockResolvedValue(
      mkResp({ left_paragraphs: [], right_paragraphs: [], matches: [] }),
    );
    renderAt("/reports/1/1/compare/text?bidder_a=1&bidder_b=2");

    await waitFor(() => {
      expect(screen.getByText("无可对比的同类文档")).toBeInTheDocument();
    });
  });

  it("缺少参数 → 自动尝试从 pair 列表挑第一个 text_similarity pair", async () => {
    // mock pair 列表返空 → 触发 noPairsFallback 提示
    vi.spyOn(api, "getReportPairs").mockResolvedValue({
      items: [],
      total: 0,
    });
    renderAt("/reports/1/1/compare/text");
    await waitFor(() => {
      // 应看到友好的 "去对比总览" 引导,不再是技术性"缺少参数"
      expect(screen.getByText("去对比总览")).toBeInTheDocument();
    });
  });
});
