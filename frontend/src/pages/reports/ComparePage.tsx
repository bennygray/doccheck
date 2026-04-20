/**
 * C15 pair 对比入口页 — C16 扩展 Tab 导航
 * 三个对比子 Tab: 总览(pair 列表) | 报价 | 元数据 | 文本
 */
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Card, Empty, Spin, Table, Tag, Typography } from "antd";
import type { TableProps } from "antd";

import CompareSubTabs from "../../components/reports/CompareSubTabs";
import ReportNavBar from "../../components/reports/ReportNavBar";
import { ApiError, api } from "../../services/api";
import type { PairComparisonItem } from "../../types";

const DIMENSION_LABELS: Record<string, string> = {
  text_similarity: "文本相似度",
  section_similarity: "章节相似度",
  structure_similarity: "结构相似度",
  metadata_author: "元数据·作者",
  metadata_time: "元数据·时间",
  metadata_machine: "元数据·机器",
  price_consistency: "报价一致性",
  price_anomaly: "报价异常",
  error_consistency: "错误一致性",
  image_reuse: "图片复用",
  style: "语言风格",
};

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

  const columns: TableProps<PairComparisonItem>["columns"] = [
    {
      title: "维度",
      dataIndex: "dimension",
      key: "dimension",
      width: 160,
      render: (d: string) => (
        <span>
          {DIMENSION_LABELS[d] ?? d}
          <Typography.Text
            type="secondary"
            style={{ fontSize: 11, marginLeft: 6, fontFamily: "monospace" }}
          >
            {d}
          </Typography.Text>
        </span>
      ),
    },
    {
      title: "投标 A",
      dataIndex: "bidder_a_id",
      key: "a",
      width: 90,
      render: (v: number) => (
        <Typography.Text style={{ fontFamily: "monospace" }}>#{v}</Typography.Text>
      ),
    },
    {
      title: "投标 B",
      dataIndex: "bidder_b_id",
      key: "b",
      width: 90,
      render: (v: number) => (
        <Typography.Text style={{ fontFamily: "monospace" }}>#{v}</Typography.Text>
      ),
    },
    {
      title: "分数",
      dataIndex: "score",
      key: "score",
      width: 100,
      align: "right" as const,
      render: (s: number) => (
        <Typography.Text
          strong
          style={{
            fontSize: 15,
            color:
              s >= 70 ? "#c53030" : s >= 40 ? "#c27c0e" : "#5c6370",
          }}
        >
          {s.toFixed(1)}
        </Typography.Text>
      ),
      sorter: (a, b) => a.score - b.score,
      defaultSortOrder: "descend" as const,
    },
    {
      title: "铁证",
      dataIndex: "is_ironclad",
      key: "ironclad",
      width: 80,
      render: (v: boolean) =>
        v ? (
          <Tag color="error" style={{ margin: 0, fontWeight: 600 }}>
            铁证
          </Tag>
        ) : (
          <span style={{ color: "#b1b6bf" }}>—</span>
        ),
    },
    {
      title: "证据摘要",
      dataIndex: "evidence_summary",
      key: "summary",
      render: (s: string | null) =>
        s ? (
          <Typography.Text style={{ fontSize: 13, color: "#5c6370" }}>
            {s}
          </Typography.Text>
        ) : (
          <span style={{ color: "#b1b6bf" }}>—</span>
        ),
    },
    {
      title: "操作",
      key: "actions",
      width: 100,
      render: (_: unknown, it) =>
        it.dimension === "text_similarity" && it.score > 0 ? (
          <Link
            to={`${basePath}/text?bidder_a=${it.bidder_a_id}&bidder_b=${it.bidder_b_id}`}
            style={{ color: "#1d4584", fontSize: 13 }}
            title="查看文本对比"
          >
            文本对比 →
          </Link>
        ) : null,
    },
  ];

  return (
    <div>
      <ReportNavBar
        projectId={projectId ?? ""}
        version={version ?? ""}
        title="投标人对比"
        subtitle="按维度 × 投标人对的命中评分,点击 '文本对比' 进入段落级对照"
        tabKey="compare"
      />

      <Card
        variant="outlined"
        styles={{ body: { padding: 0 } }}
      >
        <CompareSubTabs
          projectId={projectId ?? ""}
          version={version ?? ""}
          activeKey="overview"
        />

        {loading ? (
          <div style={{ padding: 48, textAlign: "center" }}>
            <Spin tip="加载中..." />
          </div>
        ) : error ? (
          <div style={{ padding: 32 }}>
            <Empty description={<span style={{ color: "#c53030" }}>{error}</span>} />
          </div>
        ) : items.length === 0 ? (
          <div style={{ padding: 32 }}>
            <Empty description="无对比数据" />
          </div>
        ) : (
          <Table<PairComparisonItem>
            rowKey="id"
            columns={columns}
            dataSource={items}
            rowClassName={(r) => (r.is_ironclad ? "ironclad-row" : "")}
            pagination={
              items.length > 20
                ? { pageSize: 20, showSizeChanger: false }
                : false
            }
            size="middle"
            style={{ border: "none" }}
          />
        )}
      </Card>
    </div>
  );
}

export default ComparePage;
