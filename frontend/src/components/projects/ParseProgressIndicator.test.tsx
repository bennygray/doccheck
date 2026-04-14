/**
 * L1: ParseProgressIndicator (C5 §10.3)
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import ParseProgressIndicator from "./ParseProgressIndicator";

const DEFAULT_PROGRESS = {
  total_bidders: 4,
  pending_count: 0,
  extracting_count: 0,
  extracted_count: 1,
  identifying_count: 0,
  identified_count: 1,
  pricing_count: 0,
  priced_count: 2,
  partial_count: 0,
  failed_count: 0,
  needs_password_count: 0,
};

describe("ParseProgressIndicator", () => {
  it("progress=null 不渲染", () => {
    const { container } = render(
      <ParseProgressIndicator progress={null} connected />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("渲染总数与阶段计数", () => {
    render(
      <ParseProgressIndicator progress={DEFAULT_PROGRESS} connected />,
    );
    expect(screen.getByTestId("progress-total")).toHaveTextContent("共 4");
    // 已识别 = identified + priced + pricing
    expect(screen.getByTestId("progress-identified")).toHaveTextContent("3");
    expect(screen.getByTestId("progress-priced")).toHaveTextContent("2");
  });

  it("partial 与 failed 有值时显示对应徽章", () => {
    render(
      <ParseProgressIndicator
        progress={{ ...DEFAULT_PROGRESS, partial_count: 1, failed_count: 2 }}
        connected
      />,
    );
    expect(screen.getByTestId("progress-partial")).toBeInTheDocument();
    expect(screen.getByTestId("progress-failed")).toBeInTheDocument();
  });

  it("connected=false 显示轮询兜底", () => {
    render(
      <ParseProgressIndicator
        progress={DEFAULT_PROGRESS}
        connected={false}
      />,
    );
    expect(screen.getByTestId("progress-connection")).toHaveTextContent(
      "轮询兜底",
    );
  });

  it("connected=true 显示实时", () => {
    render(
      <ParseProgressIndicator progress={DEFAULT_PROGRESS} connected />,
    );
    expect(screen.getByTestId("progress-connection")).toHaveTextContent(
      "实时",
    );
  });
});
