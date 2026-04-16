/**
 * C6 ReportPage — Tab1 骨架
 *
 * - 顶栏:风险等级徽章 + 总分
 * - 主体:10 维度得分列表(按 is_ironclad desc + best_score desc)
 * - LLM 结论:占位卡片(C14 接真 LLM)
 * - 不做:雷达图 / 热力图 / Markdown / 4 Tab(留 C14)
 */
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { ExportButton } from "../../components/reports/ExportButton";
import { ReviewPanel } from "../../components/reports/ReviewPanel";
import { ApiError, api } from "../../services/api";
import type { ReportResponse, RiskLevel } from "../../types";

const LLM_FALLBACK_PREFIX = "AI 综合研判暂不可用";

const RISK_COLORS: Record<RiskLevel, string> = {
  high: "bg-red-600 text-white",
  medium: "bg-orange-500 text-white",
  low: "bg-green-600 text-white",
};

const RISK_LABELS: Record<RiskLevel, string> = {
  high: "高风险",
  medium: "中风险",
  low: "低风险",
};

export function ReportPage() {
  const { projectId, version } = useParams<{
    projectId: string;
    version: string;
  }>();
  const navigate = useNavigate();
  const [report, setReport] = useState<ReportResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(() => {
    if (!projectId || !version) return;
    setLoading(true);
    api
      .getReport(projectId, version)
      .then((r) => {
        setReport(r);
        setError(null);
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 404) {
          setError("报告不存在或正在生成");
        } else {
          setError("加载报告失败");
        }
      })
      .finally(() => setLoading(false));
  }, [projectId, version]);

  useEffect(() => {
    reload();
  }, [reload]);

  if (loading) {
    return <div className="p-4">加载中...</div>;
  }

  if (error || !report) {
    return (
      <div className="p-4">
        <div className="text-red-600">{error || "报告不存在"}</div>
        <button
          type="button"
          className="mt-2 text-blue-600 underline"
          onClick={() => navigate(-1)}
        >
          返回
        </button>
      </div>
    );
  }

  const isLlmFallback = report.llm_conclusion.startsWith(LLM_FALLBACK_PREFIX);

  return (
    <div className="p-4 max-w-4xl mx-auto">
      {/* 顶栏 */}
      <div className="flex items-center justify-between mb-4 border-b pb-3">
        <h1 className="text-2xl font-bold">检测报告 v{report.version}</h1>
        <div className="flex items-center gap-3">
          <span
            className={`px-3 py-1 rounded font-bold ${
              RISK_COLORS[report.risk_level as RiskLevel] || "bg-gray-400"
            }`}
          >
            {RISK_LABELS[report.risk_level as RiskLevel] || report.risk_level}
          </span>
          <span className="text-3xl font-bold">
            {report.total_score.toFixed(1)}
          </span>
          <ExportButton projectId={projectId!} version={version!} />
        </div>
      </div>

      {/* C15:降级 banner 哨兵(C14 前缀契约) */}
      {isLlmFallback && (
        <div
          role="alert"
          className="mb-4 p-3 bg-yellow-50 border border-yellow-300 rounded text-sm text-yellow-900"
          data-testid="llm-fallback-banner"
        >
          ⚠ {report.llm_conclusion}
        </div>
      )}

      {/* LLM 结论:如果非降级即渲染正文 */}
      {!isLlmFallback && report.llm_conclusion && (
        <div className="mb-4 p-3 bg-gray-50 rounded border text-gray-700 whitespace-pre-wrap">
          {report.llm_conclusion}
        </div>
      )}
      {!isLlmFallback && !report.llm_conclusion && (
        <div className="mb-4 p-3 bg-gray-100 rounded text-gray-500 italic">
          AI 综合研判尚未生成
        </div>
      )}

      {/* 子页导航 */}
      <div className="mb-4 flex gap-3 text-sm">
        <Link
          to={`/reports/${projectId}/${version}/dim`}
          className="text-blue-600 underline"
        >
          维度明细
        </Link>
        <Link
          to={`/reports/${projectId}/${version}/compare`}
          className="text-blue-600 underline"
        >
          对比入口
        </Link>
        <Link
          to={`/reports/${projectId}/${version}/logs`}
          className="text-blue-600 underline"
        >
          检测日志
        </Link>
      </div>

      {/* 人工复核 */}
      <div className="mb-4">
        <ReviewPanel
          projectId={projectId!}
          version={version!}
          current={{
            status: report.manual_review_status,
            comment: report.manual_review_comment,
            reviewer_id: report.reviewer_id,
            reviewed_at: report.reviewed_at,
          }}
          onSubmitted={reload}
        />
      </div>

      {/* 10 维度得分列表 */}
      <div className="border rounded">
        <div className="px-3 py-2 bg-gray-50 font-medium border-b">
          维度得分
        </div>
        <ul>
          {report.dimensions.map((d) => (
            <li
              key={d.dimension}
              className={`px-3 py-2 border-b last:border-b-0 flex items-center justify-between ${
                d.is_ironclad ? "bg-red-50 font-bold" : ""
              }`}
            >
              <div>
                <span className="font-mono text-sm">{d.dimension}</span>
                {d.is_ironclad && (
                  <span className="ml-2 text-xs bg-red-600 text-white px-1 py-0.5 rounded">
                    铁证
                  </span>
                )}
                {d.summaries.length > 0 && (
                  <div className="text-xs text-gray-600 mt-1">
                    {d.summaries[0]}
                  </div>
                )}
              </div>
              <div className="flex items-center gap-3 text-sm">
                <span className="text-gray-500">
                  ✓{d.status_counts.succeeded} ⊘{d.status_counts.skipped} ✗
                  {d.status_counts.failed} ⏰{d.status_counts.timeout}
                </span>
                <span className="text-lg font-semibold w-16 text-right">
                  {d.best_score.toFixed(1)}
                </span>
              </div>
            </li>
          ))}
        </ul>
      </div>

      <div className="mt-3 text-xs text-gray-500">
        报告生成于 {new Date(report.created_at).toLocaleString()}
      </div>
    </div>
  );
}

export default ReportPage;
