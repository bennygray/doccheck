/**
 * C16 报价对比页 — 全项目级矩阵(US-7.2)
 *
 * - 行=报价项 列=投标人
 * - 偏差 <1% 标红
 * - 底部总报价行
 * - 列排序(点列头切换)
 * - "只看异常项" toggle
 *
 * data-testid 保留:anomaly-toggle / price-table
 */
import type * as React from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import {
  Card,
  Checkbox,
  Empty,
  Spin,
  Table,
  Tooltip,
  Typography,
} from "antd";
import type { TableProps } from "antd";

import CompareSubTabs from "../../components/reports/CompareSubTabs";
import ReportNavBar from "../../components/reports/ReportNavBar";
import { ApiError, api } from "../../services/api";
import { colors } from "../../theme/tokens";
import type { PriceCompareResponse, PriceRow } from "../../types";
import { isTenderBaselineEnabled } from "../../utils/featureFlags";

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
  const baselineEnabled = isTenderBaselineEnabled();

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

  if (loading) {
    return (
      <div>
        <ReportNavBar
          projectId={projectId ?? ""}
          version={version ?? ""}
          title="报价对比"
          tabKey="compare"
        />
        <Card>
          <div style={{ padding: 48, textAlign: "center" }}>
            <Spin tip="加载中..." />
          </div>
        </Card>
      </div>
    );
  }

  if (error) {
    return (
      <div>
        <ReportNavBar
          projectId={projectId ?? ""}
          version={version ?? ""}
          title="报价对比"
          tabKey="compare"
        />
        <Card>
          <Empty description={<span style={{ color: "#c53030" }}>{error}</span>} />
        </Card>
      </div>
    );
  }

  if (!data) return null;

  // 动态生成 Table columns:报价项 + 单位 + 每投标人一列 + 均价
  type PriceTableRow = PriceRow & { _key: number };

  const columns: TableProps<PriceTableRow>["columns"] = [
    {
      title: "报价项",
      dataIndex: "item_name",
      key: "item_name",
      width: 240,
      render: (v: string) => (
        <Typography.Text strong style={{ fontSize: 13 }}>
          {v}
        </Typography.Text>
      ),
    },
    {
      title: "单位",
      dataIndex: "unit",
      key: "unit",
      width: 80,
      render: (u: string | null) =>
        u ? <span>{u}</span> : <span style={{ color: "#b1b6bf" }}>—</span>,
    },
    ...data.bidders.map((b, i) => ({
      title: (
        <span
          style={{ cursor: "pointer", userSelect: "none" }}
          onClick={() => handleSort(i)}
        >
          {b.bidder_name}
          {sortCol === i ? (sortAsc ? " ↑" : " ↓") : ""}
        </span>
      ),
      key: `bidder-${b.bidder_id}`,
      width: 130,
      align: "right" as const,
      render: (_: unknown, row: PriceTableRow) => {
        const cell = row.cells[i];
        const isAnomaly =
          cell?.deviation_pct !== null &&
          cell?.deviation_pct !== undefined &&
          Math.abs(cell.deviation_pct) < 1;
        const tooltip =
          cell?.deviation_pct !== null && cell?.deviation_pct !== undefined
            ? `偏差 ${cell.deviation_pct.toFixed(2)}%`
            : undefined;
        const content =
          cell?.unit_price !== null && cell?.unit_price !== undefined ? (
            <span
              style={{
                fontWeight: isAnomaly ? 600 : 400,
                color: isAnomaly ? "#c53030" : "#1f2328",
                padding: isAnomaly ? "2px 8px" : 0,
                background: isAnomaly ? "#fdecec" : "transparent",
                borderRadius: isAnomaly ? 4 : 0,
              }}
            >
              {cell.unit_price.toLocaleString()}
            </span>
          ) : (
            <span style={{ color: "#b1b6bf" }}>—</span>
          );
        return tooltip ? <Tooltip title={tooltip}>{content}</Tooltip> : content;
      },
    })),
    {
      title: "均价",
      key: "mean",
      width: 110,
      align: "right" as const,
      render: (_: unknown, row: PriceTableRow) =>
        row.mean_unit_price !== null ? (
          <Typography.Text type="secondary" style={{ fontSize: 13 }}>
            {row.mean_unit_price.toLocaleString()}
          </Typography.Text>
        ) : (
          <span style={{ color: "#b1b6bf" }}>—</span>
        ),
    },
  ];

  const rows: PriceTableRow[] = displayItems.map((r, idx) => ({ ...r, _key: idx }));

  return (
    <div>
      <ReportNavBar
        projectId={projectId!}
        version={version!}
        title="报价对比"
        subtitle="行为报价项,列为投标人;偏差 < 1% 的单元格标红提示围标嫌疑"
        tabKey="compare"
        extra={
          <Checkbox
            checked={onlyAnomalies}
            onChange={(e) => setOnlyAnomalies(e.target.checked)}
            data-testid="anomaly-toggle"
          >
            只看异常项
          </Checkbox>
        }
      />

      <Card variant="outlined" styles={{ body: { padding: 0 } }}>
        <CompareSubTabs
          projectId={projectId!}
          version={version!}
          activeKey="price"
        />

        {data.bidders.length === 0 ? (
          <div style={{ padding: 32 }}>
            <Empty description="无报价数据" />
          </div>
        ) : (
          <>
            <Table<PriceTableRow>
              rowKey="_key"
              columns={columns}
              dataSource={rows}
              pagination={false}
              size="middle"
              style={{ border: "none" }}
              rowClassName={(r) => {
                const baselineRow =
                  baselineEnabled && r.baseline_matched === true;
                if (baselineRow) return "price-baseline-row";
                return r.has_anomaly ? "price-anomaly-row bg-red-50" : "";
              }}
              onRow={(r) => {
                const baselineRow =
                  baselineEnabled && r.baseline_matched === true;
                if (!baselineRow) return {};
                return {
                  style: { background: colors.bgTemplate },
                } as React.HTMLAttributes<HTMLElement>;
              }}
              // 保留 price-table data-testid 兼容契约
              components={{
                body: {
                  wrapper: (props: React.HTMLAttributes<HTMLTableSectionElement>) => (
                    <tbody {...props} data-testid="price-table" />
                  ),
                },
              }}
              summary={() => (
                <Table.Summary fixed>
                  <Table.Summary.Row
                    style={{ background: "#fafbfc", fontWeight: 600 }}
                  >
                    <Table.Summary.Cell index={0} colSpan={2}>
                      总报价
                    </Table.Summary.Cell>
                    {data.totals.map((cell, i) => (
                      <Table.Summary.Cell
                        key={cell.bidder_id}
                        index={i + 2}
                        align="right"
                      >
                        {cell.total_price !== null
                          ? cell.total_price.toLocaleString()
                          : "—"}
                      </Table.Summary.Cell>
                    ))}
                    <Table.Summary.Cell index={data.totals.length + 2} />
                  </Table.Summary.Row>
                </Table.Summary>
              )}
            />
            {displayItems.length === 0 && data.items.length > 0 && (
              <div
                style={{
                  padding: 20,
                  textAlign: "center",
                  color: "#8a919d",
                  fontSize: 13,
                }}
              >
                无异常项(所有偏差 ≥ 1%)
              </div>
            )}
          </>
        )}
      </Card>
    </div>
  );
}

export default PriceComparePage;
