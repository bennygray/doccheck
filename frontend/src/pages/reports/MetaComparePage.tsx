/**
 * C16 元数据对比页 — 全项目级矩阵(US-7.3)
 *
 * - 行=字段 列=投标人
 * - 相同值按 color_group 着色
 * - is_common 标灰 + tooltip
 * - 高敏字段(template)匹配红色强调
 * - 时间字段格式化
 *
 * data-testid 保留:meta-table / common-cell
 */
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { Card, Empty, Spin, Typography } from "antd";

import CompareSubTabs from "../../components/reports/CompareSubTabs";
import ReportNavBar from "../../components/reports/ReportNavBar";
import { ApiError, api } from "../../services/api";
import { colors } from "../../theme/tokens";
import type { MetaCompareResponse } from "../../types";
import { isTenderBaselineEnabled } from "../../utils/featureFlags";

/** color_group → 颜色(克制,不霓虹) */
const GROUP_COLORS = [
  "rgba(29, 69, 132, 0.12)",   // 品牌蓝
  "rgba(194, 124, 14, 0.12)",  // 琥珀
  "rgba(45, 122, 74, 0.12)",   // 墨绿
  "rgba(136, 58, 109, 0.12)",  // 酒红
  "rgba(90, 87, 163, 0.12)",   // 靛青
  "rgba(170, 108, 57, 0.12)",  // 铜
  "rgba(39, 124, 140, 0.12)",  // 青灰
  "rgba(166, 83, 117, 0.12)",  // 豆沙红
];

function groupBgColor(group: number | null): string | undefined {
  if (group === null) return undefined;
  return GROUP_COLORS[group % GROUP_COLORS.length];
}

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
  const baselineEnabled = isTenderBaselineEnabled();

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

  return (
    <div>
      <ReportNavBar
        projectId={projectId ?? ""}
        version={version ?? ""}
        title="元数据对比"
        subtitle="跨投标人的文档元数据矩阵,同色表示值相同,高敏字段冲突会用红色加粗强调"
        tabKey="compare"
      />

      <Card variant="outlined" styles={{ body: { padding: 0 } }}>
        <CompareSubTabs
          projectId={projectId ?? ""}
          version={version ?? ""}
          activeKey="metadata"
        />

        {loading ? (
          <div style={{ padding: 48, textAlign: "center" }}>
            <Spin tip="加载中..." />
          </div>
        ) : error ? (
          <div style={{ padding: 32 }}>
            <Empty description={<span style={{ color: "#c53030" }}>{error}</span>} />
          </div>
        ) : !data || data.bidders.length === 0 ? (
          <div style={{ padding: 32 }}>
            <Empty description="无元数据" />
          </div>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table
              data-testid="meta-table"
              style={{
                width: "100%",
                borderCollapse: "collapse",
                fontSize: 13,
              }}
            >
              <thead>
                <tr>
                  <th
                    style={{
                      padding: "10px 16px",
                      textAlign: "left",
                      background: "#fafbfc",
                      color: "#5c6370",
                      fontWeight: 500,
                      borderBottom: "1px solid #e4e7ed",
                      letterSpacing: 0.3,
                    }}
                  >
                    字段
                  </th>
                  {data.bidders.map((b) => (
                    <th
                      key={b.bidder_id}
                      style={{
                        padding: "10px 16px",
                        textAlign: "left",
                        background: "#fafbfc",
                        color: "#5c6370",
                        fontWeight: 500,
                        borderBottom: "1px solid #e4e7ed",
                        letterSpacing: 0.3,
                      }}
                    >
                      {b.bidder_name}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.fields.map((field, rowIdx) => (
                  <tr
                    key={field.field_name}
                    style={{
                      borderBottom: "1px solid #f0f2f5",
                      background: rowIdx % 2 === 1 ? "#fafbfc" : undefined,
                    }}
                  >
                    <td
                      style={{
                        padding: "10px 16px",
                        fontWeight: 500,
                        color: "#1f2328",
                      }}
                    >
                      {field.display_name}
                    </td>
                    {field.values.map((cell, i) => {
                      const isHighSensitivity =
                        HIGH_SENSITIVITY_FIELDS.has(field.field_name) &&
                        !cell.is_common &&
                        cell.color_group !== null;
                      // detect-tender-baseline §7.13:模板段灰底优先(覆盖 group/common 颜色)
                      const baselineHit =
                        baselineEnabled && cell.baseline_matched === true;
                      const bg = baselineHit
                        ? colors.bgTemplate
                        : isHighSensitivity
                          ? "#fdecec"
                          : cell.is_common
                            ? undefined
                            : groupBgColor(cell.color_group);
                      return (
                        <td
                          key={data.bidders[i].bidder_id}
                          style={{
                            padding: "10px 16px",
                            color: cell.is_common ? "#b1b6bf" : "#1f2328",
                            fontWeight: isHighSensitivity ? 600 : 400,
                            background: bg,
                          }}
                          title={
                            baselineHit
                              ? `模板段(${cell.baseline_source ?? "none"})— 已剔除`
                              : cell.is_common
                                ? "通用值,已过滤"
                                : undefined
                          }
                          data-testid={cell.is_common ? "common-cell" : undefined}
                          data-baseline-matched={baselineHit ? "true" : undefined}
                        >
                          {formatValue(field.field_name, cell.value)}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
            <div
              style={{
                padding: "12px 16px",
                borderTop: "1px solid #f0f2f5",
                fontSize: 11.5,
                color: "#8a919d",
                background: "#fafbfc",
              }}
            >
              <Typography.Text type="secondary" style={{ fontSize: 11.5 }}>
                图例:同色 = 同组相同值;灰字 = 通用值(已过滤);红底加粗 = 高敏字段冲突(如模板)
              </Typography.Text>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}

export default MetaComparePage;
