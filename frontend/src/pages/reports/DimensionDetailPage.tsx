/**
 * C15 维度明细页 — 11 维度 evidence_summary + 维度级复核 inline
 */
import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { ApiError, api } from "../../services/api";
import type {
  DimensionReviewAction,
  ReportDimensionDetail,
} from "../../types";

const ACTION_LABELS: Record<DimensionReviewAction, string> = {
  confirmed: "确认",
  rejected: "排除",
  note: "备注",
};

export function DimensionDetailPage() {
  const { projectId, version } = useParams<{
    projectId: string;
    version: string;
  }>();
  const [dims, setDims] = useState<ReportDimensionDetail[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(() => {
    if (!projectId || !version) return;
    setLoading(true);
    api
      .getReportDimensions(projectId, version)
      .then((r) => {
        setDims(r.dimensions);
        setError(null);
      })
      .catch((err) => {
        setError(
          err instanceof ApiError ? `加载失败 (${err.status})` : "加载失败",
        );
      })
      .finally(() => setLoading(false));
  }, [projectId, version]);

  useEffect(() => {
    reload();
  }, [reload]);

  const markDim = async (
    dim: string,
    action: DimensionReviewAction,
    comment: string,
  ) => {
    try {
      await api.postDimensionReview(projectId!, version!, dim, {
        action,
        comment: comment || undefined,
      });
      reload();
    } catch (err) {
      alert(
        err instanceof ApiError
          ? `标记失败 (${err.status})`
          : "标记失败",
      );
    }
  };

  if (loading) return <div className="p-4">加载中...</div>;
  if (error) return <div className="p-4 text-red-600">{error}</div>;

  return (
    <div className="p-4 max-w-4xl mx-auto">
      <h1 className="text-xl font-bold mb-4">11 维度明细</h1>
      <ul className="space-y-2">
        {dims.map((d) => (
          <li key={d.dimension} className="p-3 border rounded">
            <div className="flex items-center justify-between">
              <div>
                <span className="font-mono">{d.dimension}</span>
                {d.is_ironclad && (
                  <span className="ml-2 text-xs bg-red-600 text-white px-1 rounded">
                    铁证
                  </span>
                )}
              </div>
              <span className="font-semibold">{d.best_score.toFixed(1)}</span>
            </div>
            {d.evidence_summary && (
              <div className="mt-1 text-sm text-gray-600">
                {d.evidence_summary}
              </div>
            )}
            {d.manual_review_json ? (
              <div className="mt-2 text-xs bg-yellow-50 p-2 rounded">
                已标记 <b>{ACTION_LABELS[d.manual_review_json.action]}</b>
                {d.manual_review_json.comment && (
                  <> — {d.manual_review_json.comment}</>
                )}
              </div>
            ) : (
              <div className="mt-2 flex gap-2 text-xs">
                {(["confirmed", "rejected", "note"] as DimensionReviewAction[]).map(
                  (a) => (
                    <button
                      key={a}
                      type="button"
                      className="px-2 py-1 border rounded hover:bg-gray-100"
                      onClick={() => {
                        const cmt = window.prompt(
                          `维度 ${d.dimension} — ${ACTION_LABELS[a]} 备注(可空)`,
                          "",
                        );
                        if (cmt === null) return; // 取消
                        void markDim(d.dimension, a, cmt);
                      }}
                    >
                      {ACTION_LABELS[a]}
                    </button>
                  ),
                )}
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

export default DimensionDetailPage;
