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

  it("LLM 占位卡片可见", async () => {
    vi.spyOn(api, "getReport").mockResolvedValue(mkReport());
    renderAt("/reports/1/1");
    await waitFor(() => {
      expect(
        screen.getByText(/AI 综合研判暂不可用/),
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
      const badge = screen.getByText("高风险");
      expect(badge).toHaveClass("bg-red-600");
    });
  });
});
