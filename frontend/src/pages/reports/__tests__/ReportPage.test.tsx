import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ReportPage from "../ReportPage";
import { ApiError, api } from "../../../services/api";
import type { ReportResponse } from "../../../types";

const renderAt = (path: string) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/reports/:projectId/:version" element={<ReportPage />} />
      </Routes>
    </MemoryRouter>,
  );

const mkReport = (
  overrides: Partial<ReportResponse> = {},
): ReportResponse => ({
  version: 1,
  total_score: 67.5,
  risk_level: "medium",
  llm_conclusion: "",
  created_at: new Date().toISOString(),
  dimensions: [
    {
      dimension: "text_similarity",
      best_score: 42.5,
      is_ironclad: false,
      status_counts: { succeeded: 1, failed: 0, timeout: 0, skipped: 0 },
      summaries: ["dummy text_similarity"],
    },
    {
      dimension: "price_consistency",
      best_score: 90,
      is_ironclad: true,
      status_counts: { succeeded: 1, failed: 0, timeout: 0, skipped: 0 },
      summaries: [],
    },
  ],
  // C15 新字段:默认未复核
  manual_review_status: null,
  manual_review_comment: null,
  reviewer_id: null,
  reviewed_at: null,
  ...overrides,
});

describe("ReportPage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("渲染风险等级徽章 + 总分", async () => {
    vi.spyOn(api, "getReport").mockResolvedValue(mkReport());
    renderAt("/reports/1/1");
    await waitFor(() => {
      expect(screen.getByText(/中风险/)).toBeInTheDocument();
      expect(screen.getByText("67.5")).toBeInTheDocument();
    });
  });

  it("铁证维度显示铁证标签", async () => {
    vi.spyOn(api, "getReport").mockResolvedValue(mkReport());
    renderAt("/reports/1/1");
    await waitFor(() => {
      expect(screen.getByText("铁证")).toBeInTheDocument();
    });
  });

  it("LLM 为空时显示'尚未生成'占位", async () => {
    vi.spyOn(api, "getReport").mockResolvedValue(mkReport());
    renderAt("/reports/1/1");
    await waitFor(() => {
      expect(
        screen.getByText(/AI 综合研判尚未生成/),
      ).toBeInTheDocument();
    });
  });

  it("C15 降级 banner:llm_conclusion 以哨兵前缀开头时渲染", async () => {
    vi.spyOn(api, "getReport").mockResolvedValue(
      mkReport({
        llm_conclusion: "AI 综合研判暂不可用(LLM 超时)— 以下内容基于规则公式",
      }),
    );
    renderAt("/reports/1/1");
    await waitFor(() => {
      const banner = screen.getByTestId("llm-fallback-banner");
      expect(banner).toBeInTheDocument();
      expect(banner.textContent).toContain("AI 综合研判暂不可用");
    });
  });

  it("C15 降级 banner:llm_conclusion 非哨兵时不渲染", async () => {
    vi.spyOn(api, "getReport").mockResolvedValue(
      mkReport({
        llm_conclusion: "本项目围标风险较高,建议进一步审查。",
      }),
    );
    renderAt("/reports/1/1");
    await waitFor(() => {
      expect(
        screen.queryByTestId("llm-fallback-banner"),
      ).not.toBeInTheDocument();
      expect(
        screen.getByText(/本项目围标风险较高/),
      ).toBeInTheDocument();
    });
  });

  it("404 显示回退提示", async () => {
    vi.spyOn(api, "getReport").mockRejectedValue(new ApiError(404, "nf"));
    renderAt("/reports/1/99");
    await waitFor(() => {
      expect(
        screen.getByText(/报告不存在或正在生成/),
      ).toBeInTheDocument();
    });
  });

  it("高风险红色徽章", async () => {
    vi.spyOn(api, "getReport").mockResolvedValue(
      mkReport({ risk_level: "high", total_score: 85 }),
    );
    renderAt("/reports/1/1");
    await waitFor(() => {
      // antd 重设计后风险徽章是 Tag,用 inline style 设红色背景;
      // 检查文本渲染 + 最近 Tag 节点的 style 含主色
      const badge = screen.getByText("高风险");
      const tag = badge.closest(".ant-tag") as HTMLElement;
      expect(tag).not.toBeNull();
      expect(tag.style.background.toLowerCase()).toContain("rgb(197, 48, 48)");
    });
  });
});
