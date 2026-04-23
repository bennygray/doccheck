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
