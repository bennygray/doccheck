/**
 * C16 报价对比页 — 全项目级矩阵(US-7.2)
 *
 * - 行=报价项 列=投标人
 * - 偏差 <1% 标红
 * - 底部总报价行
 * - 列排序
 * - "只看异常项" toggle
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { ApiError, api } from "../../services/api";
import type { PriceCompareResponse, PriceRow } from "../../types";

export function PriceComparePage() {
  const { projectId, version } = useParams<{
    projectId: string;
    version: string;
  }>();

  const [data, setData] = useState<PriceCompareResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [onlyAnomalies, setOnlyAnomalies] = useState(false);
  const [sortCol, setSortCol] = useState<number | null>(null);
  const [sortAsc, setSortAsc] = useState(true);

  useEffect(() => {
    if (!projectId) return;
    setLoading(true);
    api
      .getComparePrice(projectId, version)
      .then((r) => {
        setData(r);
        setError(null);
      })
      .catch((err) => {
        setError(
          err instanceof ApiError ? `加载失败 (${err.status})` : "加载失败",
        );
      })
      .finally(() => setLoading(false));
  }, [projectId, version]);

  const handleSort = useCallback(
    (colIdx: number) => {
      if (sortCol === colIdx) {
        setSortAsc((v) => !v);
      } else {
        setSortCol(colIdx);
        setSortAsc(true);
      }
    },
    [sortCol],
  );

  const displayItems = useMemo(() => {
    if (!data) return [];
    let items: PriceRow[] = data.items;
    if (onlyAnomalies) {
      items = items.filter((r) => r.has_anomaly);
    }
    if (sortCol !== null) {
      items = [...items].sort((a, b) => {
        const va = a.cells[sortCol]?.unit_price ?? -Infinity;
        const vb = b.cells[sortCol]?.unit_price ?? -Infinity;
        return sortAsc ? va - vb : vb - va;
      });
    }
    return items;
  }, [data, onlyAnomalies, sortCol, sortAsc]);

  const basePath = `/reports/${projectId}/${version}/compare`;

  if (loading) return <div className="p-4">加载中...</div>;
  if (error) return <div className="p-4 text-red-600">{error}</div>;
  if (!data) return null;

  return (
    <div className="p-4 max-w-7xl mx-auto">
      {/* Tab 栏 */}
      <div className="flex gap-2 mb-4 border-b pb-2">
        <Link
          to={basePath}
          className="px-3 py-1 text-gray-600 hover:text-blue-600 text-sm"
        >
          对比总览
        </Link>
        <span className="px-3 py-1 bg-blue-100 text-blue-700 rounded-t font-medium text-sm">
          报价对比
        </span>
        <Link
          to={`${basePath}/metadata`}
          className="px-3 py-1 text-gray-600 hover:text-blue-600 text-sm"
        >
          元数据对比
        </Link>
      </div>

      <div className="flex items-center justify-between mb-4">
        <h1 className="text-xl font-bold">报价对比</h1>
        <label className="flex items-center gap-2 text-sm cursor-pointer">
          <input
            type="checkbox"
            checked={onlyAnomalies}
            onChange={(e) => setOnlyAnomalies(e.target.checked)}
            data-testid="anomaly-toggle"
          />
          只看异常项
        </label>
      </div>

      {data.bidders.length === 0 ? (
        <div className="text-gray-500 p-8 text-center border rounded">
          无报价数据
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm border" data-testid="price-table">
            <thead className="bg-gray-100">
              <tr>
                <th className="p-2 text-left">报价项</th>
                <th className="p-2 text-left">单位</th>
                {data.bidders.map((b, i) => (
                  <th
                    key={b.bidder_id}
                    className="p-2 text-right cursor-pointer hover:bg-gray-200"
                    onClick={() => handleSort(i)}
                  >
                    {b.bidder_name}
                    {sortCol === i ? (sortAsc ? " ↑" : " ↓") : ""}
                  </th>
                ))}
                <th className="p-2 text-right">均价</th>
              </tr>
            </thead>
            <tbody>
              {displayItems.map((row, rowIdx) => (
                <tr key={rowIdx} className={row.has_anomaly ? "bg-red-50" : ""}>
                  <td className="p-2">{row.item_name}</td>
                  <td className="p-2 text-gray-500">{row.unit || "—"}</td>
                  {row.cells.map((cell) => {
                    const isAnomaly =
                      cell.deviation_pct !== null &&
                      Math.abs(cell.deviation_pct) < 1;
                    return (
                      <td
                        key={cell.bidder_id}
                        className={`p-2 text-right ${isAnomaly ? "bg-red-200 font-semibold" : ""}`}
                        title={
                          cell.deviation_pct !== null
                            ? `偏差: ${cell.deviation_pct.toFixed(2)}%`
                            : undefined
                        }
                      >
                        {cell.unit_price !== null
                          ? cell.unit_price.toLocaleString()
                          : "—"}
                      </td>
                    );
                  })}
                  <td className="p-2 text-right text-gray-600">
                    {row.mean_unit_price !== null
                      ? row.mean_unit_price.toLocaleString()
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
            {/* 总报价行 */}
            <tfoot className="bg-gray-50 font-semibold">
              <tr>
                <td className="p-2" colSpan={2}>
                  总报价
                </td>
                {data.totals.map((cell) => (
                  <td key={cell.bidder_id} className="p-2 text-right">
                    {cell.total_price !== null
                      ? cell.total_price.toLocaleString()
                      : "—"}
                  </td>
                ))}
                <td className="p-2" />
              </tr>
            </tfoot>
          </table>
        </div>
      )}

      {displayItems.length === 0 && data.items.length > 0 && (
        <div className="mt-3 text-gray-500 text-sm">
          无异常项(所有偏差 ≥1%)
        </div>
      )}
    </div>
  );
}

export default PriceComparePage;
