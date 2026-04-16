/**
 * C16 元数据对比页 — 全项目级矩阵(US-7.3)
 *
 * - 行=字段 列=投标人
 * - 相同值按 color_group 着色
 * - is_common 标灰 + tooltip
 * - 模板/指纹匹配红色标记
 * - 时间格式化
 */
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { ApiError, api } from "../../services/api";
import type { MetaCompareResponse } from "../../types";

// color_group → 前端颜色
const GROUP_COLORS = [
  "rgba(59,130,246,0.2)",   // blue
  "rgba(234,179,8,0.2)",    // yellow
  "rgba(16,185,129,0.2)",   // green
  "rgba(244,63,94,0.2)",    // rose
  "rgba(168,85,247,0.2)",   // purple
  "rgba(249,115,22,0.2)",   // orange
  "rgba(6,182,212,0.2)",    // cyan
  "rgba(236,72,153,0.2)",   // pink
];

function groupBgColor(group: number | null): string | undefined {
  if (group === null) return undefined;
  return GROUP_COLORS[group % GROUP_COLORS.length];
}

// 高敏字段:template 匹配用红色
const HIGH_SENSITIVITY_FIELDS = new Set(["template"]);

function formatValue(fieldName: string, value: string | null): string {
  if (value === null || value === "") return "—";
  if (
    (fieldName === "doc_created_at" || fieldName === "doc_modified_at") &&
    value.includes("T")
  ) {
    try {
      const d = new Date(value);
      return d.toLocaleString("zh-CN", {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch {
      return value;
    }
  }
  return value;
}

export function MetaComparePage() {
  const { projectId, version } = useParams<{
    projectId: string;
    version: string;
  }>();

  const [data, setData] = useState<MetaCompareResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!projectId) return;
    setLoading(true);
    api
      .getCompareMetadata(projectId, version)
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
        <Link
          to={`${basePath}/price`}
          className="px-3 py-1 text-gray-600 hover:text-blue-600 text-sm"
        >
          报价对比
        </Link>
        <span className="px-3 py-1 bg-blue-100 text-blue-700 rounded-t font-medium text-sm">
          元数据对比
        </span>
      </div>

      <h1 className="text-xl font-bold mb-4">元数据对比</h1>

      {data.bidders.length === 0 ? (
        <div className="text-gray-500 p-8 text-center border rounded">
          无元数据
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm border" data-testid="meta-table">
            <thead className="bg-gray-100">
              <tr>
                <th className="p-2 text-left">字段</th>
                {data.bidders.map((b) => (
                  <th key={b.bidder_id} className="p-2 text-left">
                    {b.bidder_name}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.fields.map((field) => (
                <tr key={field.field_name}>
                  <td className="p-2 font-medium">{field.display_name}</td>
                  {field.values.map((cell, i) => {
                    const isHighSensitivity =
                      HIGH_SENSITIVITY_FIELDS.has(field.field_name) &&
                      !cell.is_common &&
                      cell.color_group !== null;

                    return (
                      <td
                        key={data.bidders[i].bidder_id}
                        className={`p-2 ${cell.is_common ? "text-gray-400" : ""} ${isHighSensitivity ? "font-semibold" : ""}`}
                        style={{
                          backgroundColor: isHighSensitivity
                            ? "rgba(239,68,68,0.2)"
                            : cell.is_common
                              ? undefined
                              : groupBgColor(cell.color_group),
                        }}
                        title={
                          cell.is_common
                            ? "通用值,已过滤"
                            : undefined
                        }
                        data-testid={
                          cell.is_common ? "common-cell" : undefined
                        }
                      >
                        {formatValue(field.field_name, cell.value)}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default MetaComparePage;
