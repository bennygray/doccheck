/**
 * C6 DetectProgressIndicator — antd 化:Progress 进度条 + 一行摘要 + "查看报告"
 */
import { Button, Progress, Space, Typography } from "antd";
import { CheckCircleOutlined, FileTextOutlined, SyncOutlined } from "@ant-design/icons";
import type { AgentTask, ProjectAnalysisReport } from "../../types";

const TERMINAL_STATUSES = new Set<AgentTask["status"]>([
  "succeeded",
  "failed",
  "timeout",
  "skipped",
]);

export interface DetectProgressIndicatorProps {
  agentTasks: AgentTask[];
  connected: boolean;
  latestReport: ProjectAnalysisReport | null;
  onViewReport?: (version: number) => void;
}

export function DetectProgressIndicator({
  agentTasks,
  connected,
  latestReport,
  onViewReport,
}: DetectProgressIndicatorProps) {
  const total = agentTasks.length;
  const completed = agentTasks.filter((t) =>
    TERMINAL_STATUSES.has(t.status),
  ).length;
  const pct = total > 0 ? Math.round((completed / total) * 100) : 0;

  const latest = [...agentTasks]
    .filter((t) => TERMINAL_STATUSES.has(t.status))
    .sort((a, b) => (b.finished_at || "").localeCompare(a.finished_at || ""))
    .at(0);

  const allDone = total > 0 && completed === total;

  return (
    <div
      style={{
        padding: 14,
        background: "#fafbfc",
        border: "1px solid #e4e7ed",
        borderRadius: 8,
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 8,
        }}
      >
        <Space size={6}>
          {allDone ? (
            <CheckCircleOutlined style={{ color: "#2d7a4a" }} />
          ) : (
            <SyncOutlined spin style={{ color: "#1d4584" }} />
          )}
          <Typography.Text strong style={{ fontSize: 13 }}>
            {allDone ? "检测完成" : "检测进行中"}
          </Typography.Text>
        </Space>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {completed}/{total} 维度完成
        </Typography.Text>
      </div>

      <Progress
        percent={pct}
        strokeColor={allDone ? "#2d7a4a" : "#1d4584"}
        trailColor="#e4e7ed"
        size="small"
        showInfo={false}
      />

      {latest && (
        <Typography.Paragraph
          type="secondary"
          style={{ fontSize: 12.5, margin: "8px 0 0" }}
        >
          最新: <Typography.Text strong style={{ fontSize: 12.5 }}>{latest.agent_name}</Typography.Text>
          {" · "}
          {latest.status}
          {latest.summary ? ` — ${latest.summary}` : ""}
        </Typography.Paragraph>
      )}

      {!connected && (
        <Typography.Text
          type="secondary"
          style={{ fontSize: 11, display: "block", marginTop: 4 }}
        >
          实时更新离线,轮询中
        </Typography.Text>
      )}

      {allDone && latestReport && (
        <div style={{ marginTop: 12 }}>
          <Button
            type="primary"
            icon={<FileTextOutlined />}
            onClick={() => onViewReport?.(latestReport.version)}
            style={{ background: "#2d7a4a", borderColor: "#2d7a4a" }}
          >
            查看报告
          </Button>
        </div>
      )}
    </div>
  );
}
