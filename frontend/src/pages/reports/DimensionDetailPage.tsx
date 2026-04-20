/**
 * C15 维度明细页 — 11 维度 evidence + 维度级复核 inline
 *
 * 视觉:ReportNavBar + 维度卡片列表(每维度 Card),复核改用 Popconfirm + 备注输入
 * 业务契约:action/comment 参数签名不变
 */
import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import {
  App,
  Button,
  Card,
  Empty,
  Form,
  Input,
  Modal,
  Space,
  Spin,
  Tag,
  Typography,
} from "antd";

import ReportNavBar from "../../components/reports/ReportNavBar";
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

const ACTION_TAG_COLORS: Record<DimensionReviewAction, string> = {
  confirmed: "success",
  rejected: "default",
  note: "blue",
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

export function DimensionDetailPage() {
  const { projectId, version } = useParams<{
    projectId: string;
    version: string;
  }>();
  const { message } = App.useApp();
  const [dims, setDims] = useState<ReportDimensionDetail[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // 当前弹框:对哪个维度执行哪个动作
  const [reviewModal, setReviewModal] = useState<{
    dim: string;
    action: DimensionReviewAction;
  } | null>(null);
  const [reviewComment, setReviewComment] = useState("");
  const [submitting, setSubmitting] = useState(false);

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

  async function submitReview() {
    if (!reviewModal || !projectId || !version) return;
    setSubmitting(true);
    try {
      await api.postDimensionReview(projectId, version, reviewModal.dim, {
        action: reviewModal.action,
        comment: reviewComment.trim() || undefined,
      });
      void message.success("已标记");
      setReviewModal(null);
      setReviewComment("");
      reload();
    } catch (err) {
      void message.error(
        err instanceof ApiError ? `标记失败 (${err.status})` : "标记失败",
      );
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) {
    return (
      <div style={{ padding: 48, textAlign: "center" }}>
        <Spin tip="加载中..." />
      </div>
    );
  }

  if (error) {
    return (
      <div>
        <ReportNavBar
          projectId={projectId ?? ""}
          version={version ?? ""}
          title="维度明细"
          tabKey="dim"
        />
        <Card>
          <Empty description={<span style={{ color: "#c53030" }}>{error}</span>} />
        </Card>
      </div>
    );
  }

  return (
    <div>
      <ReportNavBar
        projectId={projectId!}
        version={version!}
        title="维度明细"
        subtitle="查看各维度证据摘要,可对单个维度执行人工复核"
        tabKey="dim"
      />

      <Space direction="vertical" size={12} style={{ width: "100%" }}>
        {dims.map((d) => (
          <Card
            key={d.dimension}
            variant="outlined"
            styles={{ body: { padding: 16 } }}
            style={{
              borderLeft: d.is_ironclad ? "3px solid #c53030" : undefined,
              background: d.is_ironclad ? "#fef8f8" : undefined,
            }}
          >
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "flex-start",
                gap: 12,
                marginBottom: 8,
              }}
            >
              <div style={{ flex: 1, minWidth: 0 }}>
                <Space size={8} align="center">
                  <Typography.Text strong style={{ fontSize: 15 }}>
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
              </div>
              <Typography.Text
                strong
                style={{
                  fontSize: 20,
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
            </div>

            {d.evidence_summary && (
              <Typography.Paragraph
                style={{
                  fontSize: 13,
                  color: "#5c6370",
                  margin: "0 0 12px",
                  lineHeight: 1.7,
                }}
              >
                {d.evidence_summary}
              </Typography.Paragraph>
            )}

            {d.manual_review_json ? (
              <div
                style={{
                  padding: "8px 12px",
                  background: "#fcf3e3",
                  borderRadius: 6,
                  border: "1px solid #f0e0b0",
                  fontSize: 12.5,
                  color: "#1f2328",
                }}
              >
                已标记{" "}
                <Tag
                  color={ACTION_TAG_COLORS[d.manual_review_json.action]}
                  style={{ margin: "0 4px" }}
                >
                  {ACTION_LABELS[d.manual_review_json.action]}
                </Tag>
                {d.manual_review_json.comment && (
                  <span style={{ color: "#5c6370" }}>
                    — {d.manual_review_json.comment}
                  </span>
                )}
              </div>
            ) : (
              <Space size={6}>
                {(
                  ["confirmed", "rejected", "note"] as DimensionReviewAction[]
                ).map((a) => (
                  <Button
                    key={a}
                    size="small"
                    onClick={() => {
                      setReviewComment("");
                      setReviewModal({ dim: d.dimension, action: a });
                    }}
                  >
                    {ACTION_LABELS[a]}
                  </Button>
                ))}
              </Space>
            )}
          </Card>
        ))}
      </Space>

      <Modal
        open={!!reviewModal}
        title={
          reviewModal
            ? `${ACTION_LABELS[reviewModal.action]} · ${DIMENSION_LABELS[reviewModal.dim] ?? reviewModal.dim}`
            : ""
        }
        onCancel={() => {
          setReviewModal(null);
          setReviewComment("");
        }}
        okText="提交"
        cancelText="取消"
        confirmLoading={submitting}
        onOk={() => void submitReview()}
        destroyOnHidden
      >
        <Form layout="vertical">
          <Form.Item label="备注(可空)">
            <Input.TextArea
              value={reviewComment}
              onChange={(e) => setReviewComment(e.target.value)}
              rows={3}
              placeholder="可填写复核原因或说明"
              maxLength={500}
              showCount
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

export default DimensionDetailPage;
