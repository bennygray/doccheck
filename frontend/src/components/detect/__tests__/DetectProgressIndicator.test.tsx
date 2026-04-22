import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DetectProgressIndicator } from "../DetectProgressIndicator";
import type { AgentTask, ProjectAnalysisReport } from "../../../types";

const mkTask = (overrides: Partial<AgentTask> = {}): AgentTask => ({
  id: 1,
  agent_name: "text_similarity",
  agent_type: "pair",
  pair_bidder_a_id: 1,
  pair_bidder_b_id: 2,
  status: "pending",
  started_at: null,
  finished_at: null,
  elapsed_ms: null,
  score: null,
  summary: null,
  error: null,
  ...overrides,
});

describe("DetectProgressIndicator", () => {
  it("空列表仍渲染占位", () => {
    render(
      <DetectProgressIndicator
        agentTasks={[]}
        connected={true}
        latestReport={null}
      />,
    );
    expect(screen.getByText(/检测进行中/)).toBeInTheDocument();
    expect(screen.getByText("0/0 维度完成")).toBeInTheDocument();
  });

  it("进度条 3/10 显示 30%", () => {
    const tasks = [
      ...Array.from({ length: 3 }, (_, i) =>
        mkTask({ id: i, status: "succeeded" as const }),
      ),
      ...Array.from({ length: 7 }, (_, i) =>
        mkTask({ id: i + 3, status: "pending" as const }),
      ),
    ];
    render(
      <DetectProgressIndicator
        agentTasks={tasks}
        connected={true}
        latestReport={null}
      />,
    );
    expect(screen.getByText("3/10 维度完成")).toBeInTheDocument();
    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "30");
  });

  it("离线状态显示轮询提示(running 态)", () => {
    // 新版:离线 banner 只在未全完成时展示(allDone 后已在绿卡,不再提示离线)
    render(
      <DetectProgressIndicator
        agentTasks={[
          mkTask({ id: 1, status: "succeeded" }),
          mkTask({ id: 2, status: "pending" }),
        ]}
        connected={false}
        latestReport={null}
      />,
    );
    expect(screen.getByText(/实时更新离线/)).toBeInTheDocument();
  });

  it("全部完成 + latestReport 存在 → 显示查看报告按钮", () => {
    const onViewReport = vi.fn();
    const latestReport: ProjectAnalysisReport = {
      version: 3,
      total_score: 72.5,
      risk_level: "high",
      created_at: new Date().toISOString(),
    };
    const tasks = [
      mkTask({ id: 1, status: "succeeded", finished_at: "2026-01-01T00:00:00Z" }),
    ];
    render(
      <DetectProgressIndicator
        agentTasks={tasks}
        connected={true}
        latestReport={latestReport}
        onViewReport={onViewReport}
      />,
    );
    const btn = screen.getByRole("button", { name: /查看报告/ });
    fireEvent.click(btn);
    expect(onViewReport).toHaveBeenCalledWith(3);
  });
});
