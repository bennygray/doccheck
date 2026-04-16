/**
 * C15 检测 + 操作日志页 — 合并 AgentTask + AuditLog,按时间倒序
 */
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

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

  if (loading) return <div className="p-4">加载中...</div>;
  if (error) return <div className="p-4 text-red-600">{error}</div>;

  return (
    <div className="p-4 max-w-5xl mx-auto">
      <div className="flex items-center justify-between mb-3">
        <h1 className="text-xl font-bold">检测 + 操作日志</h1>
        <select
          className="border rounded px-2 py-1 text-sm"
          value={source}
          onChange={(e) => setSource(e.target.value as SourceFilter)}
        >
          <option value="all">全部</option>
          <option value="agent_task">检测执行</option>
          <option value="audit_log">人工操作</option>
        </select>
      </div>
      <ul className="space-y-1">
        {items.map((e, i) => (
          <li
            key={`${e.source}-${i}-${e.created_at}`}
            className={`p-2 border rounded text-xs ${
              e.source === "audit_log" ? "bg-blue-50" : "bg-white"
            }`}
          >
            <div className="flex items-center justify-between">
              <span className="font-mono text-gray-500">
                [{e.source}] {new Date(e.created_at).toLocaleString()}
              </span>
            </div>
            <pre className="mt-1 whitespace-pre-wrap">
              {JSON.stringify(e.payload, null, 2)}
            </pre>
          </li>
        ))}
      </ul>
      {items.length === 0 && (
        <div className="mt-3 text-gray-500 text-sm">无日志</div>
      )}
    </div>
  );
}

export default AuditLogPage;
