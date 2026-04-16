/**
 * C15 ReviewPanel — 整报告级人工复核表单
 *
 * - 未复核:显示 status 选择 + comment + 提交按钮
 * - 已复核:显示当前复核结论,允许点击"修改"再次复核
 * - 表单校验:status 必选,comment 可空
 *
 * 注意:复核成功后不改 total_score / risk_level(D11)
 */
import { useState } from "react";

import { ApiError, api } from "../../services/api";
import type { ReviewStatus } from "../../types";

const STATUS_OPTIONS: Array<{ value: ReviewStatus; label: string }> = [
  { value: "confirmed", label: "确认围标" },
  { value: "rejected", label: "排除围标" },
  { value: "downgraded", label: "降级风险" },
  { value: "upgraded", label: "升级风险" },
];

const STATUS_LABELS: Record<ReviewStatus, string> = Object.fromEntries(
  STATUS_OPTIONS.map((o) => [o.value, o.label]),
) as Record<ReviewStatus, string>;

interface Props {
  projectId: number | string;
  version: number | string;
  current: {
    status: ReviewStatus | null;
    comment: string | null;
    reviewer_id: number | null;
    reviewed_at: string | null;
  };
  onSubmitted?: () => void;
}

export function ReviewPanel({ projectId, version, current, onSubmitted }: Props) {
  const [editing, setEditing] = useState(current.status === null);
  const [status, setStatus] = useState<ReviewStatus | "">(
    current.status ?? "",
  );
  const [comment, setComment] = useState(current.comment ?? "");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!status) {
      setError("请选择复核结论");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await api.postReview(projectId, version, {
        status,
        comment: comment || undefined,
      });
      setEditing(false);
      onSubmitted?.();
    } catch (err) {
      setError(
        err instanceof ApiError ? `提交失败 (${err.status})` : "提交失败",
      );
    } finally {
      setSubmitting(false);
    }
  };

  if (!editing && current.status) {
    return (
      <div className="p-3 border rounded bg-gray-50">
        <div className="flex items-center justify-between mb-2">
          <span className="font-semibold">人工复核结论</span>
          <button
            type="button"
            className="text-blue-600 text-sm underline"
            onClick={() => setEditing(true)}
          >
            修改
          </button>
        </div>
        <div className="text-sm">
          <div>
            结论:<span className="font-bold">{STATUS_LABELS[current.status]}</span>
          </div>
          {current.comment && (
            <div className="mt-1 text-gray-700">评论:{current.comment}</div>
          )}
          {current.reviewed_at && (
            <div className="mt-1 text-xs text-gray-500">
              {new Date(current.reviewed_at).toLocaleString()} by user#{current.reviewer_id}
            </div>
          )}
        </div>
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="p-3 border rounded bg-white space-y-2">
      <div className="font-semibold">人工复核</div>
      <div>
        <label className="text-sm mr-2">结论:</label>
        <select
          className="border rounded px-2 py-1 text-sm"
          value={status}
          onChange={(e) => setStatus(e.target.value as ReviewStatus)}
          disabled={submitting}
        >
          <option value="">请选择</option>
          {STATUS_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label className="text-sm block mb-1">评论(可选):</label>
        <textarea
          className="w-full border rounded px-2 py-1 text-sm"
          rows={2}
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          disabled={submitting}
        />
      </div>
      {error && <div className="text-red-600 text-sm">{error}</div>}
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={submitting}
          className="px-3 py-1 bg-blue-600 text-white rounded disabled:opacity-50"
        >
          {submitting ? "提交中..." : "提交复核"}
        </button>
        {current.status && (
          <button
            type="button"
            className="px-3 py-1 text-gray-500"
            onClick={() => setEditing(false)}
            disabled={submitting}
          >
            取消
          </button>
        )}
      </div>
    </form>
  );
}

export default ReviewPanel;
