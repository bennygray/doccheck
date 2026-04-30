/**
 * L1: BaselineStatusBadge(detect-tender-baseline §7.16)
 *
 * 覆盖:tender→L1 蓝 / consensus→L2 琥珀 / metadata_cluster→L3 灰 / none→L3 灰 + warnings 提示
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import BaselineStatusBadge, {
  baselineSourceToStatus,
} from "./BaselineStatusBadge";

describe("baselineSourceToStatus", () => {
  it("source=tender → L1", () => {
    expect(baselineSourceToStatus("tender")).toBe("L1");
  });
  it("source=consensus → L2", () => {
    expect(baselineSourceToStatus("consensus")).toBe("L2");
  });
  it("source=metadata_cluster → L3", () => {
    expect(baselineSourceToStatus("metadata_cluster")).toBe("L3");
  });
  it("source=none/null/undefined → L3", () => {
    expect(baselineSourceToStatus("none")).toBe("L3");
    expect(baselineSourceToStatus(null)).toBe("L3");
    expect(baselineSourceToStatus(undefined)).toBe("L3");
  });
});

describe("BaselineStatusBadge", () => {
  it("tender 渲染 L1 标签 + dataset 标 L1", () => {
    render(<BaselineStatusBadge source="tender" />);
    const badge = screen.getByTestId("baseline-status-badge");
    expect(badge).toHaveTextContent("L1");
    expect(badge.getAttribute("data-baseline-status")).toBe("L1");
  });

  it("consensus 渲染 L2 标签", () => {
    render(<BaselineStatusBadge source="consensus" />);
    const badge = screen.getByTestId("baseline-status-badge");
    expect(badge).toHaveTextContent("L2");
    expect(badge.getAttribute("data-baseline-status")).toBe("L2");
  });

  it("none 渲染 L3 标签", () => {
    render(<BaselineStatusBadge source="none" />);
    const badge = screen.getByTestId("baseline-status-badge");
    expect(badge).toHaveTextContent("L3");
    expect(badge.getAttribute("data-baseline-status")).toBe("L3");
  });
});
