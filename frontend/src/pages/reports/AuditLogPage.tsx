/**
 * C15 检测 + 操作日志页 — 合并 AgentTask + AuditLog,按时间倒序
 *
 * 视觉:ReportNavBar + Source 筛选 + Timeline 样式日志列表
 */
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import {
  Card,
  Empty,
  Radio,
  Space,
  Spin,
  Tag,
  Typography,
} from "antd";

import ReportNavBar from "../../components/reports/ReportNavBar";
import { ApiError, api } from "../../services/api";
import type { LogEntry } from "../../types";

type SourceFilter = "all" | "agent_task" | "audit_log";

export function AuditLogPage() {
  const { projectId, version } = useParams<{
    projectId: string;
    version: string;
  }>();
  const [source, setSource] = useState<SourceFilter>("all");
  const [items, setItems] = useState<LogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!projectId || !version) return;
    setLoading(true);
    api
      .getReportLogs(projectId, version, source, 200)
      .then((r) => {
        setItems(r.items);
        setError(null);
      })
      .catch((err) => {
        setError(
          err instanceof ApiError ? `加载失败 (${err.status})` : "加载失败",
        );
      })
      .finally(() => setLoading(false));
  }, [projectId, version, source]);

  return (
    <div>
      <ReportNavBar
        projectId={projectId ?? ""}
        version={version ?? ""}
        title="检测日志"
        subtitle="检测执行记录与人工操作审计,按时间倒序"
        tabKey="logs"
        extra={
          <Radio.Group
            value={source}
            onChange={(e) => setSource(e.target.value as SourceFilter)}
            optionType="button"
            buttonStyle="solid"
            options={[
              { label: "全部", value: "all" },
              { label: "检测执行", value: "agent_task" },
              { label: "人工操作", value: "audit_log" },
            ]}
          />
        }
      />

      {loading ? (
        <Card>
          <div style={{ padding: 48, textAlign: "center" }}>
            <Spin tip="加载中..." />
          </div>
        </Card>
      ) : error ? (
        <Card>
          <Empty description={<span style={{ color: "#c53030" }}>{error}</span>} />
        </Card>
      ) : items.length === 0 ? (
        <Card>
          <Empty description="暂无日志" />
        </Card>
      ) : (
        <Card variant="outlined" styles={{ body: { padding: 0 } }}>
          <Space
            direction="vertical"
            size={0}
            style={{ width: "100%" }}
          >
            {items.map((e, i) => (
              <div
                key={`${e.source}-${i}-${e.created_at}`}
                style={{
                  padding: "12px 16px",
                  borderBottom:
                    i < items.length - 1 ? "1px solid #f0f2f5" : "none",
                  background:
                    e.source === "audit_log" ? "#f7faff" : "#ffffff",
                  display: "flex",
                  gap: 12,
                  alignItems: "flex-start",
                }}
              >
                <div
                  style={{
                    width: 3,
                    alignSelf: "stretch",
                    background:
                      e.source === "audit_log" ? "#1d4584" : "#e4e7ed",
                    borderRadius: 2,
                    flexShrink: 0,
                  }}
                  aria-hidden="true"
                />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <Space
                    size={8}
                    style={{ marginBottom: 6, flexWrap: "wrap" }}
                  >
                    <Tag
                      color={e.source === "audit_log" ? "blue" : "default"}
                      style={{ margin: 0, fontSize: 11 }}
                    >
                      {e.source === "audit_log" ? "人工操作" : "检测执行"}
                    </Tag>
                    <Typography.Text
                      type="secondary"
                      style={{ fontSize: 12, fontFamily: "monospace" }}
                    >
                      {new Date(e.created_at).toLocaleString()}
                    </Typography.Text>
                  </Space>
                  <pre
                    style={{
                      margin: 0,
                      fontSize: 11.5,
                      color: "#1f2328",
                      background: "#fafbfc",
                      padding: "8px 10px",
                      borderRadius: 4,
                      border: "1px solid #ebedf0",
                      whiteSpace: "pre-wrap",
                      wordBreak: "break-word",
                      fontFamily:
                        '"SF Mono", Menlo, Consolas, "Courier New", monospace',
                    }}
                  >
                    {JSON.stringify(e.payload, null, 2)}
                  </pre>
                </div>
              </div>
            ))}
          </Space>
        </Card>
      )}
    </div>
  );
}

export default AuditLogPage;
