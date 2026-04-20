/**
 * C6/C14/C15 ReportPage —— 检测报告总览(完整 antd 重设计)
 *
 * 视觉:ReportNavBar(面包屑+标题+Tab)+ 风险评分顶部卡 + LLM 结论卡 + 维度列表
 *
 * 业务契约 0 变动:
 *   - 加载 / 404 / LLM fallback 前缀哨兵 / 铁证标记
 *   - ExportButton / ReviewPanel 子组件原样嵌入
 *   - data-testid="llm-fallback-banner" 保留
 */
import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  Alert,
  Badge,
  Button,
  Card,
  Empty,
  List,
  Space,
  Spin,
  Tag,
  Typography,
} from "antd";
import { ExclamationCircleOutlined } from "@ant-design/icons";

import { ExportButton } from "../../components/reports/ExportButton";
import { ReviewPanel } from "../../components/reports/ReviewPanel";
import ReportNavBar from "../../components/reports/ReportNavBar";
import { ApiError, api } from "../../services/api";
import type { ReportResponse, RiskLevel } from "../../types";

const LLM_FALLBACK_PREFIX = "AI 综合研判暂不可用";

const RISK_META: Record<
  RiskLevel,
  { label: string; color: string; bg: string; border: string }
> = {
  high: { label: "高风险", color: "#c53030", bg: "#fdecec", border: "#c53030" },
  medium: { label: "中风险", color: "#c27c0e", bg: "#fcf3e3", border: "#c27c0e" },
  low: { label: "低风险", color: "#2d7a4a", bg: "#e8f3ec", border: "#2d7a4a" },
};

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
    return (
      <div style={{ padding: 48, textAlign: "center" }}>
        <Spin tip="加载报告中..." />
      </div>
    );
  }

  if (error || !report) {
    return (
      <div>
        <ReportNavBar
          projectId={projectId ?? ""}
          version={version ?? ""}
          title="检测报告"
          tabKey={null}
        />
        <Card>
          <Empty description={error || "报告不存在"}>
            <Button onClick={() => navigate(-1)}>返回</Button>
          </Empty>
        </Card>
      </div>
    );
  }

  const isLlmFallback = report.llm_conclusion.startsWith(LLM_FALLBACK_PREFIX);
  const risk = RISK_META[report.risk_level as RiskLevel] ?? RISK_META.low;

  return (
    <div>
      <ReportNavBar
        projectId={projectId!}
        version={version!}
        title={`检测报告 v${report.version}`}
        subtitle={`生成于 ${new Date(report.created_at).toLocaleString()}`}
        tabKey="report"
        extra={
          <Space>
            <ExportButton projectId={projectId!} version={version!} />
          </Space>
        }
      />

      {/* 风险顶部卡:总分 + 等级 */}
      <Card
        variant="outlined"
        styles={{ body: { padding: 24 } }}
        style={{
          marginBottom: 16,
          background: risk.bg,
          border: `1px solid ${risk.border}33`,
          borderLeft: `4px solid ${risk.border}`,
        }}
      >
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            gap: 16,
            flexWrap: "wrap",
          }}
        >
          <div>
            <div
              style={{
                fontSize: 12,
                color: "#5c6370",
                letterSpacing: 0.5,
                marginBottom: 8,
              }}
            >
              综合研判
            </div>
            <Space size={16} align="center">
              <Tag
                style={{
                  padding: "4px 12px",
                  margin: 0,
                  fontSize: 14,
                  fontWeight: 600,
                  color: "#ffffff",
                  background: risk.color,
                  borderColor: risk.color,
                }}
              >
                {risk.label}
              </Tag>
              <span
                style={{
                  fontSize: 36,
                  fontWeight: 600,
                  color: "#1f2328",
                  lineHeight: 1.2,
                }}
              >
                {report.total_score.toFixed(1)}
              </span>
              <span style={{ fontSize: 14, color: "#5c6370" }}>/ 100</span>
            </Space>
          </div>
          <div style={{ flex: 1, minWidth: 240, maxWidth: 520 }}>
            {isLlmFallback ? (
              <Alert
                type="warning"
                icon={<ExclamationCircleOutlined />}
                showIcon
                message={report.llm_conclusion}
                data-testid="llm-fallback-banner"
              />
            ) : report.llm_conclusion ? (
              <Typography.Paragraph
                style={{
                  fontSize: 13,
                  color: "#1f2328",
                  margin: 0,
                  lineHeight: 1.7,
                  whiteSpace: "pre-wrap",
                }}
              >
                {report.llm_conclusion}
              </Typography.Paragraph>
            ) : (
              <Typography.Text italic type="secondary">
                AI 综合研判尚未生成
              </Typography.Text>
            )}
          </div>
        </div>
      </Card>

      {/* 人工复核 */}
      <Card variant="outlined" styles={{ body: { padding: 20 } }} style={{ marginBottom: 16 }}>
        <Typography.Title level={5} style={{ margin: "0 0 12px", fontWeight: 600 }}>
          人工复核
        </Typography.Title>
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
      </Card>

      {/* 维度得分列表 */}
      <Card
        variant="outlined"
        styles={{ body: { padding: 0 } }}
        title={<span style={{ fontWeight: 600 }}>维度得分</span>}
        extra={
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            共 {report.dimensions.length} 个维度
          </Typography.Text>
        }
      >
        <List
          dataSource={report.dimensions}
          renderItem={(d) => (
            <List.Item
              style={{
                padding: "14px 20px",
                background: d.is_ironclad ? "#fef8f8" : undefined,
                borderLeft: d.is_ironclad ? "3px solid #c53030" : "3px solid transparent",
              }}
            >
              <div style={{ flex: 1, minWidth: 0, marginRight: 16 }}>
                <Space size={8} style={{ marginBottom: 4 }}>
                  <Typography.Text strong style={{ fontSize: 14 }}>
                    {DIMENSION_LABELS[d.dimension] ?? d.dimension}
                  </Typography.Text>
                  <Typography.Text
                    type="secondary"
                    style={{ fontSize: 11, fontFamily: "monospace" }}
                  >
                    {d.dimension}
                  </Typography.Text>
                  {d.is_ironclad && (
                    <Tag color="error" style={{ margin: 0, fontWeight: 600 }}>
                      铁证
                    </Tag>
                  )}
                </Space>
                {d.summaries.length > 0 && (
                  <Typography.Paragraph
                    type="secondary"
                    ellipsis={{ rows: 1 }}
                    style={{ fontSize: 12.5, margin: 0 }}
                  >
                    {d.summaries[0]}
                  </Typography.Paragraph>
                )}
              </div>
              <Space size={12}>
                <Space size={4} style={{ fontSize: 11, color: "#8a919d" }}>
                  <Badge status="success" text={d.status_counts.succeeded} />
                  <Badge status="default" text={d.status_counts.skipped} />
                  <Badge status="error" text={d.status_counts.failed} />
                </Space>
                <Typography.Text
                  strong
                  style={{
                    fontSize: 18,
                    minWidth: 56,
                    textAlign: "right",
                    color:
                      d.best_score >= 70
                        ? "#c53030"
                        : d.best_score >= 40
                          ? "#c27c0e"
                          : "#5c6370",
                  }}
                >
                  {d.best_score.toFixed(1)}
                </Typography.Text>
              </Space>
            </List.Item>
          )}
        />
      </Card>
    </div>
  );
}

export default ReportPage;
