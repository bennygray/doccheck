/**
 * C15 pair 对比入口页 — C16 扩展 Tab 导航
 * Tab: 对比总览(pair 列表) | 报价对比 | 元数据对比
 */
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { ApiError, api } from "../../services/api";
import type { PairComparisonItem } from "../../types";

export function ComparePage() {
  const { projectId, version } = useParams<{
    projectId: string;
    version: string;
  }>();
  const [items, setItems] = useState<PairComparisonItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!projectId || !version) return;
    setLoading(true);
    api
      .getReportPairs(projectId, version, "score_desc", 100)
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
  }, [projectId, version]);

  const basePath = `/reports/${projectId}/${version}/compare`;

  return (
    <div className="p-4 max-w-5xl mx-auto">
      {/* Tab 栏 */}
      <div className="flex gap-2 mb-4 border-b pb-2">
        <span className="px-3 py-1 bg-blue-100 text-blue-700 rounded-t font-medium text-sm">
          对比总览
        </span>
        <Link
          to={`${basePath}/price`}
          className="px-3 py-1 text-gray-600 hover:text-blue-600 text-sm"
        >
          报价对比
        </Link>
        <Link
          to={`${basePath}/metadata`}
          className="px-3 py-1 text-gray-600 hover:text-blue-600 text-sm"
        >
          元数据对比
        </Link>
      </div>

      <h1 className="text-xl font-bold mb-4">投标人对比(pair 摘要)</h1>

      {loading && <div className="p-4">加载中...</div>}
      {error && <div className="p-4 text-red-600">{error}</div>}
      {!loading && !error && (
        <>
          <table className="w-full text-sm border">
            <thead className="bg-gray-100">
              <tr>
                <th className="p-2 text-left">维度</th>
                <th className="p-2 text-left">投标 A</th>
                <th className="p-2 text-left">投标 B</th>
                <th className="p-2 text-right">分数</th>
                <th className="p-2 text-left">铁证</th>
                <th className="p-2 text-left">证据摘要</th>
                <th className="p-2 text-left">操作</th>
              </tr>
            </thead>
            <tbody>
              {items.map((it) => (
                <tr key={it.id} className={it.is_ironclad ? "bg-red-50" : ""}>
                  <td className="p-2 font-mono">{it.dimension}</td>
                  <td className="p-2">#{it.bidder_a_id}</td>
                  <td className="p-2">#{it.bidder_b_id}</td>
                  <td className="p-2 text-right font-semibold">
                    {it.score.toFixed(1)}
                  </td>
                  <td className="p-2">{it.is_ironclad ? "是" : "—"}</td>
                  <td className="p-2 text-gray-700">
                    {it.evidence_summary || "—"}
                  </td>
                  <td className="p-2">
                    {it.dimension === "text_similarity" && it.score > 0 && (
                      <Link
                        to={`${basePath}/text?bidder_a=${it.bidder_a_id}&bidder_b=${it.bidder_b_id}`}
                        className="text-blue-600 hover:underline text-xs"
                        title="查看文本对比"
                      >
                        文本对比
                      </Link>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {items.length === 0 && (
            <div className="mt-3 text-gray-500 text-sm">无对比数据</div>
          )}
        </>
      )}
    </div>
  );
}

export default ComparePage;
