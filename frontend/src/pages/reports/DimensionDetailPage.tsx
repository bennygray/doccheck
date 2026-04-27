/**
 * C15 维度明细页 — 13 维度 evidence + 维度级复核 inline
 *
 * 视觉(v2):**按风险分层**展示,而非按学术分类。用户关心的是"哪些命中",
 * 不是"算法用了什么算法"。
 *  - 🔴 铁证(is_ironclad)
 *  - ⚠ 高风险(>= 70 且非铁证)
 *  - ● 中风险(40~69)
 *  - ○ 低风险/未命中(< 40 或 skipped)(默认折叠)
 *
 * 每条命中都带"查看证据"跳转到对应子对比页(文本/报价/元数据)。
 *
 * 业务契约:action/comment 参数签名不变,data-testid 保留
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  App,
  Button,
  Card,
  Collapse,
  Empty,
  Form,
  Input,
  Modal,
  Space,
  Spin,
  Tag,
  Typography,
} from "antd";
import { FireOutlined, RightOutlined } from "@ant-design/icons";

import ReportNavBar from "../../components/reports/ReportNavBar";
import { ApiError, api } from "../../services/api";
import type {
  DimensionReviewAction,
  ReportDimensionDetail,
} from "../../types";
import { summarizeEvidence } from "../../utils/evidenceSummary";

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
  price_total_match: "投标总额完全相等",
  price_overshoot: "超过最高限价",
};

/** 每维度的证据跳转路径 */
function evidenceHref(
  projectId: string,
  version: string,
  dim: string,
): string | null {
  const base = `/reports/${projectId}/${version}/compare`;
  if (dim === "text_similarity" || dim === "section_similarity") {
    return `${base}/text`;
  }
  if (dim === "price_consistency" || dim === "price_anomaly") {
    return `${base}/price`;
  }
  if (dim.startsWith("metadata_")) return `${base}/metadata`;
  // structure_similarity / error_consistency / image_reuse / style 无专属页,跳对比总览
  return base;
}

type RiskTier = "ironclad" | "high" | "medium" | "low";

function riskTier(d: ReportDimensionDetail): RiskTier {
  if (d.is_ironclad) return "ironclad";
  if (d.best_score >= 70) return "high";
  if (d.best_score >= 40) return "medium";
  return "low";
}

const TIER_META: Record<
  RiskTier,
  { label: string; color: string; bg: string; order: number }
> = {
  ironclad: { label: "铁证", color: "#c53030", bg: "#fdecec", order: 1 },
  high: { label: "高风险", color: "#c53030", bg: "#fef8f8", order: 2 },
  medium: { label: "中风险", color: "#c27c0e", bg: "#fcf3e3", order: 3 },
  low: { label: "低风险 / 未命中", color: "#8a919d", bg: "#fafbfc", order: 4 },
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

  /** 按风险分层,各层按 score desc 排 */
  const tiered = useMemo(() => {
    const groups: Record<RiskTier, ReportDimensionDetail[]> = {
      ironclad: [],
      high: [],
      medium: [],
      low: [],
    };
    for (const d of dims) groups[riskTier(d)].push(d);
    for (const k of Object.keys(groups) as RiskTier[]) {
      groups[k].sort((a, b) => b.best_score - a.best_score);
    }
    return groups;
  }, [dims]);

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

  const hitCount =
    tiered.ironclad.length + tiered.high.length + tiered.medium.length;

  return (
    <div>
      <ReportNavBar
        projectId={projectId!}
        version={version!}
        title="维度明细"
        subtitle={
          hitCount > 0
            ? `${hitCount} 个维度命中(${tiered.ironclad.length} 铁证 · ${tiered.high.length} 高风险 · ${tiered.medium.length} 中风险)`
            : "所有维度均未命中"
        }
        tabKey="dim"
      />

      <Space direction="vertical" size={16} style={{ width: "100%" }}>
        {/* 铁证 + 高 + 中:展开渲染 */}
        {(["ironclad", "high", "medium"] as RiskTier[]).map((tier) => {
          const items = tiered[tier];
          if (!items.length) return null;
          return (
            <TierSection
              key={tier}
              tier={tier}
              items={items}
              projectId={projectId!}
              version={version!}
              onMark={(dim, action) => {
                setReviewComment("");
                setReviewModal({ dim, action });
              }}
            />
          );
        })}

        {/* 低风险 / 未命中:折叠面板,默认收起 */}
        {tiered.low.length > 0 && (
          <Collapse
            ghost
            items={[
              {
                key: "low",
                label: (
                  <Space size={8}>
                    <span
                      style={{
                        width: 8,
                        height: 8,
                        borderRadius: "50%",
                        background: TIER_META.low.color,
                        display: "inline-block",
                      }}
                    />
                    <Typography.Text style={{ fontSize: 13, color: "#5c6370" }}>
                      低风险 / 未命中
                    </Typography.Text>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      {tiered.low.length} 个维度
                    </Typography.Text>
                  </Space>
                ),
                children: (
                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns:
                        "repeat(auto-fill, minmax(200px, 1fr))",
                      gap: 6,
                    }}
                  >
                    {tiered.low.map((d) => (
                      <div
                        key={d.dimension}
                        style={{
                          display: "flex",
                          justifyContent: "space-between",
                          padding: "8px 12px",
                          fontSize: 13,
                          color: "#5c6370",
                          border: "1px solid #ebedf0",
                          borderRadius: 6,
                          background: "#fafbfc",
                        }}
                      >
                        <span>
                          {DIMENSION_LABELS[d.dimension] ?? d.dimension}
                        </span>
                        <span style={{ color: "#8a919d" }}>
                          {d.best_score.toFixed(1)}
                        </span>
                      </div>
                    ))}
                  </div>
                ),
              },
            ]}
          />
        )}
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

/* ───────── 子组件 ───────── */

function TierSection({
  tier,
  items,
  projectId,
  version,
  onMark,
}: {
  tier: RiskTier;
  items: ReportDimensionDetail[];
  projectId: string;
  version: string;
  onMark: (dim: string, action: DimensionReviewAction) => void;
}) {
  const meta = TIER_META[tier];
  return (
    <div>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          marginBottom: 10,
          paddingLeft: 2,
        }}
      >
        {tier === "ironclad" ? (
          <FireOutlined style={{ color: meta.color, fontSize: 14 }} />
        ) : (
          <span
            style={{
              width: 8,
              height: 8,
              borderRadius: "50%",
              background: meta.color,
              display: "inline-block",
            }}
          />
        )}
        <Typography.Text
          style={{
            fontSize: 13,
            fontWeight: 600,
            color: meta.color,
            letterSpacing: 0.5,
          }}
        >
          {meta.label}
        </Typography.Text>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {items.length} 个维度
        </Typography.Text>
      </div>

      <Space direction="vertical" size={10} style={{ width: "100%" }}>
        {items.map((d) => (
          <DimensionCard
            key={d.dimension}
            d={d}
            tier={tier}
            projectId={projectId}
            version={version}
            onMark={onMark}
          />
        ))}
      </Space>
    </div>
  );
}

function DimensionEvidenceBlock({
  dimension,
  raw,
}: {
  dimension: string;
  raw: string | null | undefined;
}) {
  const [showRaw, setShowRaw] = useState(false);
  const summary = summarizeEvidence(dimension, raw);
  const hasRawJson =
    !!raw && raw.trim().startsWith("{") && summary !== raw;

  if (!summary && !raw) return null;

  return (
    <div style={{ margin: "0 0 12px" }}>
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 10,
        }}
      >
        <Typography.Paragraph
          style={{
            fontSize: 13,
            color: "#2c3139",
            margin: 0,
            lineHeight: 1.7,
            flex: 1,
          }}
        >
          {summary || raw}
        </Typography.Paragraph>
        {hasRawJson && (
          <Typography.Link
            onClick={() => setShowRaw((s) => !s)}
            style={{ fontSize: 12, color: "#8a919d", flex: "0 0 auto" }}
          >
            {showRaw ? "收起" : "原文"}
          </Typography.Link>
        )}
      </div>
      {showRaw && raw && (
        <pre
          style={{
            margin: "8px 0 0",
            padding: "10px 12px",
            fontSize: 11.5,
            lineHeight: 1.55,
            color: "#5c6370",
            background: "#fafbfc",
            border: "1px solid #f0f2f5",
            borderRadius: 4,
            whiteSpace: "pre-wrap",
            wordBreak: "break-all",
            fontFamily:
              "ui-monospace, 'SF Mono', Menlo, Consolas, monospace",
          }}
        >
          {(() => {
            try {
              return JSON.stringify(JSON.parse(raw), null, 2);
            } catch {
              return raw;
            }
          })()}
        </pre>
      )}
    </div>
  );
}

function DimensionCard({
  d,
  tier,
  projectId,
  version,
  onMark,
}: {
  d: ReportDimensionDetail;
  tier: RiskTier;
  projectId: string;
  version: string;
  onMark: (dim: string, action: DimensionReviewAction) => void;
}) {
  const isIronclad = tier === "ironclad";
  const href = evidenceHref(projectId, version, d.dimension);
  const scoreColor =
    d.best_score >= 70 ? "#c53030" : d.best_score >= 40 ? "#c27c0e" : "#5c6370";

  return (
    <Card
      variant="outlined"
      styles={{ body: { padding: 16 } }}
      style={{
        borderLeft: isIronclad ? "3px solid #c53030" : undefined,
        background: isIronclad ? "#fef8f8" : undefined,
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
            {isIronclad && (
              <Tag color="error" style={{ margin: 0, fontWeight: 600 }}>
                铁证
              </Tag>
            )}
          </Space>
        </div>
        <Typography.Text
          strong
          style={{ fontSize: 20, color: scoreColor }}
        >
          {d.best_score.toFixed(1)}
        </Typography.Text>
      </div>

      <DimensionEvidenceBlock
        dimension={d.dimension}
        raw={d.evidence_summary}
      />

      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        {d.manual_review_json ? (
          <div
            style={{
              padding: "6px 12px",
              background: "#fcf3e3",
              borderRadius: 6,
              border: "1px solid #f0e0b0",
              fontSize: 12.5,
              color: "#1f2328",
              flex: 1,
              minWidth: 0,
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
                onClick={() => onMark(d.dimension, a)}
              >
                {ACTION_LABELS[a]}
              </Button>
            ))}
          </Space>
        )}
        {href && (
          <Link to={href}>
            <Button size="small" type="link" style={{ color: "#1d4584", padding: "0 4px" }}>
              查看证据 <RightOutlined style={{ fontSize: 10 }} />
            </Button>
          </Link>
        )}
      </div>
    </Card>
  );
}

export default DimensionDetailPage;
