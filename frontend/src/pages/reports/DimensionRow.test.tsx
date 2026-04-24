/**
 * L1 - ReportPage.DimensionRow 孤立组件测试
 * (honest-detection-results I-3: review finding — 补全 F3 error_consistency 降级提示
 * 的自动化覆盖,原 Task 5.7/6.4 降级 manual 遗留的覆盖缺口)
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import type { ReportDimension } from "../../types";
import { DimensionRow } from "./ReportPage";

function makeDim(
  overrides: Partial<ReportDimension> = {},
): ReportDimension {
  return {
    dimension: "error_consistency",
    best_score: 0,
    is_ironclad: false,
    status_counts: { succeeded: 0, failed: 0, timeout: 0, skipped: 0 },
    summaries: [],
    ...overrides,
  };
}

describe("DimensionRow — F3 身份缺失降级提示", () => {
  it("error_consistency 维度 + hasInsufficientIdentity=true → 显示 Alert", () => {
    render(
      <DimensionRow
        dim={makeDim({ dimension: "error_consistency" })}
        hasInsufficientIdentity={true}
      />,
    );
    const alert = screen.getByTestId("dimension-identity-degraded");
    expect(alert).toBeInTheDocument();
    expect(alert.textContent).toContain("身份信息缺失情况下已降级判定");
  });

  it("error_consistency 维度 + hasInsufficientIdentity=false → 不显示 Alert", () => {
    render(
      <DimensionRow
        dim={makeDim({ dimension: "error_consistency" })}
        hasInsufficientIdentity={false}
      />,
    );
    expect(
      screen.queryByTestId("dimension-identity-degraded"),
    ).not.toBeInTheDocument();
  });

  it("非 error_consistency 维度(text_similarity)即使 hasInsufficientIdentity=true 也不显示 Alert", () => {
    render(
      <DimensionRow
        dim={makeDim({ dimension: "text_similarity", best_score: 25 })}
        hasInsufficientIdentity={true}
      />,
    );
    expect(
      screen.queryByTestId("dimension-identity-degraded"),
    ).not.toBeInTheDocument();
  });

  it("hasInsufficientIdentity 参数默认 false(向前兼容)", () => {
    render(
      <DimensionRow dim={makeDim({ dimension: "error_consistency" })} />,
    );
    expect(
      screen.queryByTestId("dimension-identity-degraded"),
    ).not.toBeInTheDocument();
  });
});

/**
 * harden-async-infra N7 / F1:新 skipped 文案不截断不变形
 * (design D6 规范:后端写入 AgentTask.summary,前端 DimensionRow 通过
 *  summaries[0] 原样渲染,零映射。此处参数化验证 7 条新文案在现有
 *  Typography.Paragraph ellipsis 容器里可用,不会撑破布局。)
 */
describe("DimensionRow — N7/F1 新 skipped 文案渲染(harden-async-infra)", () => {
  const newSkipSummaries = [
    "解析崩溃,已跳过",       // subprocess crash
    "解析超时,已跳过",       // subprocess timeout
    "LLM 超时,已跳过",       // LLM timeout
    "LLM 限流,已跳过",       // LLM rate_limit
    "LLM 鉴权失败,已跳过",   // LLM auth
    "LLM 网络错误,已跳过",   // LLM network
    "LLM 返回异常,已跳过",   // LLM bad_response / other
    // reviewer L4:text_similarity 的 _DEGRADED_SUMMARY(非 skipped 路径但也是降级)
    "AI 研判暂不可用,仅展示程序相似度(降级)",
  ];

  it.each(newSkipSummaries)(
    "summary=%p 原样渲染到 DimensionRow",
    (summary) => {
      render(
        <DimensionRow
          dim={makeDim({
            dimension: "text_similarity",
            summaries: [summary],
            status_counts: { succeeded: 0, failed: 0, timeout: 0, skipped: 1 },
          })}
        />,
      );
      // Typography.Paragraph ellipsis rows=1 会在超长时用 title 属性承载全文本;
      // 这里文案 ≤50 字,正常可见 & 不截断
      expect(screen.getByText(summary)).toBeInTheDocument();
    },
  );
});

/**
 * test-infra-followup-wave2 Item 6:text_similarity degraded 路径(非 skipped,
 * 保留公式相似度 + LLM 研判不可用)的真实 shape 下 DimensionRow 依然正确渲染
 * _DEGRADED_SUMMARY 文案 + 非零分数 + succeeded 计数。
 *
 * 后端契约(text_similarity.py):evidence["degraded"]=true 时 summary 置为
 * _DEGRADED_SUMMARY,AgentTask.status 仍为 succeeded(有公式结果,不走 skipped)。
 * 本 case 锁"降级非 skipped"场景的前端渲染不回归 —— 防未来改 DimensionRow 把
 * "text_sim + succeeded" 的 summaries[0] 吞掉。
 */
describe("DimensionRow — text_similarity degraded 真实场景(Item 6)", () => {
  const DEGRADED_SUMMARY = "AI 研判暂不可用,仅展示程序相似度(降级)";

  it("text_sim degraded 保留公式分数 + 渲染降级 summary", () => {
    render(
      <DimensionRow
        dim={makeDim({
          dimension: "text_similarity",
          best_score: 42.5, // 公式相似度仍产出(非零)
          is_ironclad: false,
          summaries: [DEGRADED_SUMMARY],
          // degraded 路径 status = succeeded(带公式结果),不是 skipped
          status_counts: { succeeded: 1, failed: 0, timeout: 0, skipped: 0 },
        })}
      />,
    );
    expect(screen.getByText(DEGRADED_SUMMARY)).toBeInTheDocument();
    // 分数文本由 Progress format 产出,带小数
    expect(screen.getByText("42.5")).toBeInTheDocument();
  });

  it("text_sim degraded summaries 空数组 → 不 render summary 段(graceful)", () => {
    // 防御:上游异常导致 summaries 为空,组件不崩
    const { container } = render(
      <DimensionRow
        dim={makeDim({
          dimension: "text_similarity",
          best_score: 0,
          summaries: [],
          status_counts: { succeeded: 0, failed: 0, timeout: 0, skipped: 1 },
        })}
      />,
    );
    expect(screen.queryByText(DEGRADED_SUMMARY)).not.toBeInTheDocument();
    // 组件渲染不崩(有根节点)
    expect(container.firstChild).not.toBeNull();
  });
});
