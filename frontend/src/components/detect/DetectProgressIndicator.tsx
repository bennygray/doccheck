/**
 * C6 DetectProgressIndicator —— 检测进度仪表板
 *
 * 三态切换:
 *  - starting(刚启动,agentTasks 可能为空):骨架占位 + "检测正在启动..."
 *  - running(有 agentTasks,未全完成):总进度条 + 11 维度九宫格 + 最近事件行
 *  - completed(全完成):绿底成功卡 + 大 CTA "查看报告"
 *
 * 静默离线提示:lastEventAt 超 10s 未变 + !connected → 琥珀 banner
 */
import { useEffect, useState } from "react";
import { Alert, Button, Progress, Space, Tooltip, Typography } from "antd";
import {
  CheckCircleFilled,
  CloseCircleFilled,
  ClockCircleOutlined,
  FileTextOutlined,
  LoadingOutlined,
  MinusCircleFilled,
  SyncOutlined,
} from "@ant-design/icons";

import type { AgentTask, ProjectAnalysisReport } from "../../types";

const TERMINAL_STATUSES = new Set<AgentTask["status"]>([
  "succeeded",
  "failed",
  "timeout",
  "skipped",
]);

const DIMENSION_LABELS: Record<string, string> = {
  text_similarity: "文本相似度",
  section_similarity: "章节相似度",
  structure_similarity: "结构相似度",
  metadata_author: "元数据·作者",
  metadata_time: "元数据·时间",
  metadata_machine: "元数据·机器",
  price_consistency: "报价一致性",
  price_anomaly: "报价异常",
  error_consistency: "错误一致性",
  image_reuse: "图片复用",
  style: "语言风格",
};

const STATUS_META: Record<
  AgentTask["status"],
  { icon: React.ReactNode; color: string; label: string; bg?: string }
> = {
  pending: {
    icon: <ClockCircleOutlined />,
    color: "#b1b6bf",
    label: "待执行",
  },
  running: {
    icon: <LoadingOutlined spin />,
    color: "#1d4584",
    label: "执行中",
    bg: "#eef3fb",
  },
  succeeded: {
    icon: <CheckCircleFilled />,
    color: "#2d7a4a",
    label: "成功",
    bg: "#e8f3ec",
  },
  failed: {
    icon: <CloseCircleFilled />,
    color: "#c53030",
    label: "失败",
    bg: "#fdecec",
  },
  timeout: {
    icon: <ClockCircleOutlined />,
    color: "#c27c0e",
    label: "超时",
    bg: "#fcf3e3",
  },
  skipped: {
    icon: <MinusCircleFilled />,
    color: "#8a919d",
    label: "跳过",
  },
};

export interface DetectProgressIndicatorProps {
  agentTasks: AgentTask[];
  connected: boolean;
  /** 最近事件时间戳;超 10s 无变化 + 未连接 → 显示离线提示 */
  lastEventAt?: number;
  latestReport: ProjectAnalysisReport | null;
  fallbackVersion?: number;
  /** starting 态显示骨架:点击启动后、首条 SSE 到来前 */
  justStarted?: boolean;
  onViewReport?: (version: number) => void;
  onExport?: () => void;
}

export function DetectProgressIndicator({
  agentTasks,
  connected,
  lastEventAt,
  latestReport,
  fallbackVersion,
  justStarted,
  onViewReport,
}: DetectProgressIndicatorProps) {
  const total = agentTasks.length;
  const completed = agentTasks.filter((t) =>
    TERMINAL_STATUSES.has(t.status),
  ).length;
  const running = agentTasks.filter((t) => t.status === "running").length;
  const failed = agentTasks.filter((t) => t.status === "failed").length;
  const pct = total > 0 ? Math.round((completed / total) * 100) : 0;

  // 最近完成的 agent(用于"最近事件"一行)
  const latest = [...agentTasks]
    .filter((t) => TERMINAL_STATUSES.has(t.status))
    .sort((a, b) => (b.finished_at || "").localeCompare(a.finished_at || ""))
    .at(0);

  const allDone = total > 0 && completed === total;
  const viewVersion =
    latestReport?.version ?? (allDone ? fallbackVersion ?? 1 : null);

  // 离线提示条件:
  //   - 没传 lastEventAt(测试或旧调用):connected=false 即显示(兼容行为)
  //   - 传了 lastEventAt:10s 内无事件 + 未连接 + 未全完成 → 静默型离线
  const [isStale, setIsStale] = useState(false);
  useEffect(() => {
    if (lastEventAt == null) {
      setIsStale(!connected && !allDone);
      return;
    }
    const check = () => {
      const staleNow =
        !connected && Date.now() - lastEventAt > 10_000 && !allDone;
      setIsStale(staleNow);
    };
    check();
    const t = setInterval(check, 2000);
    return () => clearInterval(t);
  }, [lastEventAt, connected, allDone]);

  /* ─── starting 态:刚启动,agentTasks 还是空 ─── */
  if (justStarted && total === 0) {
    return (
      <div
        style={{
          padding: "20px 24px",
          background: "#eef3fb",
          border: "1px solid #c9d6ea",
          borderRadius: 10,
        }}
      >
        <Space size={10} align="center">
          <LoadingOutlined spin style={{ fontSize: 20, color: "#1d4584" }} />
          <div>
            <Typography.Text strong style={{ fontSize: 14, display: "block" }}>
              检测已启动,正在初始化...
            </Typography.Text>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              正在调度 11 个维度检测 agent,首批进度几秒内出现
            </Typography.Text>
          </div>
        </Space>
      </div>
    );
  }

  /* ─── completed 态:全完成。再细分两步:
   *    (a) 无 latestReport → "综合研判生成中..."(后端 judge LLM 还在 3-10s 跑)
   *    (b) 有 latestReport → 绿底大卡 + "查看报告" 按钮
   */
  if (allDone) {
    const reportReady = latestReport !== null;
    return (
      <div
        style={{
          padding: "20px 24px",
          background: reportReady ? "#e8f3ec" : "#fcf3e3",
          border: `1px solid ${reportReady ? "#b5d9c2" : "#f0e0b0"}`,
          borderRadius: 10,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: 16,
          flexWrap: "wrap",
        }}
      >
        <Space size={12} align="center">
          {reportReady ? (
            <CheckCircleFilled style={{ fontSize: 28, color: "#2d7a4a" }} />
          ) : (
            <LoadingOutlined spin style={{ fontSize: 24, color: "#c27c0e" }} />
          )}
          <div>
            <Typography.Text
              strong
              style={{ fontSize: 15, display: "block", color: "#1f2328" }}
            >
              {reportReady ? "检测完成" : "AI 综合研判生成中..."}
            </Typography.Text>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {completed}/{total} 维度完成
              {failed > 0 ? ` · ${failed} 项失败` : ""}
              {reportReady
                ? ` · 总分 ${latestReport.total_score.toFixed(1)}`
                : " · 正在汇总得分与结论,通常需 3~10 秒"}
            </Typography.Text>
          </div>
        </Space>
        {reportReady && viewVersion !== null ? (
          <Button
            type="primary"
            size="large"
            icon={<FileTextOutlined />}
            onClick={() => onViewReport?.(viewVersion)}
            style={{ background: "#2d7a4a", borderColor: "#2d7a4a" }}
          >
            查看报告
          </Button>
        ) : (
          <Button
            type="primary"
            size="large"
            icon={<LoadingOutlined />}
            disabled
          >
            请稍候
          </Button>
        )}
      </div>
    );
  }

  /* ─── running 态:进度条 + 九宫格 + 最近事件 ─── */
  return (
    <div
      style={{
        padding: "18px 20px",
        background: "#fafbfc",
        border: "1px solid #e4e7ed",
        borderRadius: 10,
      }}
    >
      {/* 顶部:状态 + 进度条 */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 10,
          flexWrap: "wrap",
          gap: 8,
        }}
      >
        <Space size={8} align="center">
          {running > 0 ? (
            <SyncOutlined spin style={{ fontSize: 15, color: "#1d4584" }} />
          ) : (
            <SyncOutlined style={{ fontSize: 15, color: "#1d4584" }} />
          )}
          <Typography.Text strong style={{ fontSize: 14 }}>
            检测进行中
          </Typography.Text>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {completed}/{total} 维度完成
            {running > 0 ? ` · 正在执行 ${running}` : ""}
            {failed > 0 ? ` · ${failed} 项失败` : ""}
          </Typography.Text>
        </Space>
        <Typography.Text strong style={{ fontSize: 16, color: "#1d4584" }}>
          {pct}%
        </Typography.Text>
      </div>
      <Progress
        percent={pct}
        strokeColor="#1d4584"
        trailColor="#e4e7ed"
        size="default"
        showInfo={false}
        style={{ marginBottom: 14 }}
      />

      {/* 静默离线提示 */}
      {isStale && (
        <Alert
          type="warning"
          showIcon
          message="实时更新离线,正在轮询检测状态(每 3 秒)"
          style={{ marginBottom: 12 }}
        />
      )}

      {/* 11 维度九宫格 */}
      {total > 0 && (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))",
            gap: 6,
            marginBottom: 12,
          }}
        >
          {agentTasks.map((t) => {
            const meta = STATUS_META[t.status] ?? STATUS_META.pending;
            const label = DIMENSION_LABELS[t.agent_name] ?? t.agent_name;
            return (
              <Tooltip
                key={t.id}
                title={
                  <>
                    <div>{label}</div>
                    <div style={{ fontSize: 11, opacity: 0.7 }}>
                      {t.agent_name}
                    </div>
                    <div style={{ fontSize: 11 }}>状态:{meta.label}</div>
                    {t.summary && (
                      <div style={{ fontSize: 11 }}>{t.summary}</div>
                    )}
                  </>
                }
              >
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 6,
                    padding: "5px 8px",
                    borderRadius: 6,
                    background: meta.bg ?? "transparent",
                    border: meta.bg
                      ? `1px solid ${meta.bg}`
                      : "1px solid #ebedf0",
                    fontSize: 12,
                    overflow: "hidden",
                  }}
                >
                  <span
                    style={{
                      color: meta.color,
                      fontSize: 13,
                      display: "inline-flex",
                      alignItems: "center",
                    }}
                  >
                    {meta.icon}
                  </span>
                  <span
                    style={{
                      color: "#1f2328",
                      whiteSpace: "nowrap",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      flex: 1,
                      fontWeight: meta.bg ? 500 : 400,
                    }}
                  >
                    {label}
                  </span>
                </div>
              </Tooltip>
            );
          })}
        </div>
      )}

      {/* 最近事件行 */}
      {latest && (
        <div
          style={{
            fontSize: 12,
            color: "#5c6370",
            paddingTop: 10,
            borderTop: "1px dashed #ebedf0",
          }}
        >
          <span style={{ marginRight: 6 }}>▸ 最近:</span>
          <Typography.Text strong style={{ fontSize: 12 }}>
            {DIMENSION_LABELS[latest.agent_name] ?? latest.agent_name}
          </Typography.Text>
          <span
            style={{
              color: STATUS_META[latest.status]?.color ?? "#8a919d",
              margin: "0 6px",
            }}
          >
            {STATUS_META[latest.status]?.label ?? latest.status}
          </span>
          {latest.summary && (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              — {latest.summary}
            </Typography.Text>
          )}
        </div>
      )}
    </div>
  );
}
