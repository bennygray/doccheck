/**
 * C6 DetectProgressIndicator — 进度条 + 一行摘要 + 终态显示"查看报告"
 */
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

  // 最近一个完成的 AgentTask(有 finished_at 的里面取时间最新)
  const latest = [...agentTasks]
    .filter((t) => TERMINAL_STATUSES.has(t.status))
    .sort((a, b) => (b.finished_at || "").localeCompare(a.finished_at || ""))
    .at(0);

  const allDone = total > 0 && completed === total;
  const reportVersion =
    latestReport?.version ?? (allDone ? agentTasks[0]?.id ?? null : null);

  return (
    <div className="border rounded p-3 bg-gray-50">
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm font-medium">
          {allDone ? "✅ 检测完成" : "🔄 检测进行中"}
        </span>
        <span className="text-sm text-gray-600">
          {completed}/{total} 维度完成
        </span>
      </div>
      <div className="w-full bg-gray-200 rounded h-2">
        <div
          className="bg-blue-500 h-2 rounded transition-all duration-300"
          style={{ width: `${pct}%` }}
          role="progressbar"
          aria-valuenow={pct}
          aria-valuemin={0}
          aria-valuemax={100}
        />
      </div>
      {latest && (
        <div className="mt-2 text-sm text-gray-700">
          最新: {latest.agent_name} {latest.status}
          {latest.summary ? ` — ${latest.summary}` : ""}
        </div>
      )}
      {!connected && (
        <div className="mt-1 text-xs text-gray-500">
          实时更新离线,轮询中
        </div>
      )}
      {allDone && reportVersion !== null && latestReport && (
        <div className="mt-3">
          <button
            type="button"
            className="px-3 py-1 rounded bg-green-600 text-white hover:bg-green-700"
            onClick={() => onViewReport?.(latestReport.version)}
          >
            查看报告
          </button>
        </div>
      )}
    </div>
  );
}
