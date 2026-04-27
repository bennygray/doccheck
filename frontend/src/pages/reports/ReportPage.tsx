/**
 * C6/C14/C15 ReportPage —— 检测报告总览(可视化强化版)
 *
 * 视觉:
 *  - Hero 行双栏:左 Gauge 圆盘(总分+风险) + 右 Radar 雷达(13 维度风险形状)
 *  - LLM 结论卡(降级时 Alert 前缀哨兵)
 *  - 人工复核卡
 *  - 维度列表:每行带横向 Progress 条 + 色分三档 + 铁证高亮
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Progress,
  Row,
  Space,
  Spin,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import { Radar } from "@ant-design/charts";
import {
  CheckCircleFilled,
  CloseCircleFilled,
  ExclamationCircleOutlined,
  FireOutlined,
  MinusCircleFilled,
  ClockCircleOutlined,
} from "@ant-design/icons";

import { ExportButton } from "../../components/reports/ExportButton";
import { ReviewPanel } from "../../components/reports/ReviewPanel";
import ReportNavBar from "../../components/reports/ReportNavBar";
import { ApiError, api } from "../../services/api";
import type { ReportDimension, ReportResponse, RiskLevel } from "../../types";

const LLM_FALLBACK_PREFIX = "AI 综合研判暂不可用";

const RISK_META: Record<
  RiskLevel,
  { label: string; color: string; bg: string }
> = {
  high: { label: "高风险", color: "#c53030", bg: "#fdecec" },
  medium: { label: "中风险", color: "#c27c0e", bg: "#fcf3e3" },
  low: { label: "低风险", color: "#2d7a4a", bg: "#e8f3ec" },
  // honest-detection-results: 新增"证据不足"档,中性灰,区别于 low 的绿
  indeterminate: { label: "证据不足", color: "#8a919d", bg: "#f5f7fa" },
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
  // fix-bug-triple-and-direction-high 新增 2 维
  price_total_match: "投标总额完全相等",
  price_overshoot: "超过最高限价",
};

/** 雷达图轴标签(短名,省空间) */
const DIMENSION_SHORT: Record<string, string> = {
  text_similarity: "文本",
  section_similarity: "章节",
  structure_similarity: "结构",
  metadata_author: "作者",
  metadata_time: "时间",
  metadata_machine: "机器",
  price_consistency: "报价",
  price_anomaly: "报价异常",
  error_consistency: "错误",
  image_reuse: "图片",
  style: "风格",
  // fix-bug-triple-and-direction-high 新增 2 维
  price_total_match: "总额相等",
  price_overshoot: "超限",
};

function scoreColor(score: number): string {
  if (score >= 70) return "#c53030";
  if (score >= 40) return "#c27c0e";
  return "#5c6370";
}

export function ReportPage() {
  const { projectId, version } = useParams<{
    projectId: string;
    version: string;
  }>();
  const navigate = useNavigate();
  const [report, setReport] = useState<ReportResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  // honest-detection-results F3: 项目下任一 bidder identity_info_status=insufficient 时
  // error_consistency 维度显示降级提示
  const [hasInsufficientIdentity, setHasInsufficientIdentity] =
    useState<boolean>(false);

  // 404 自动重试:刚点完"检测完成"就进来时,判 LLM 还在 3-10s 跑,AR 行没写入 DB。
  // 最多重试 10 次 × 2s = 20s 窗口,够覆盖 judge.
  const [retryCount, setRetryCount] = useState(0);
  const MAX_RETRY = 10;
  const RETRY_INTERVAL_MS = 2000;

  const reload = useCallback(() => {
    if (!projectId || !version) return;
    setLoading(true);
    api
      .getReport(projectId, version)
      .then((r) => {
        setReport(r);
        setError(null);
        setRetryCount(0);
      })
      .catch(async (err) => {
        if (err instanceof ApiError && err.status === 404) {
          // honest-detection-results N4: 先问 /analysis/status 看 judge 进度,
          // 给用户更精确的文案(agent 还没完 vs judge 还在写报告)
          try {
            const status = await api.getAnalysisStatus(projectId);
            if (status.report_ready) {
              // 极少数 race:report_ready=true 但 /reports 404 — 兜底到通用文案
              setError("报告正在生成,请稍候...");
            } else {
              const agents = status.agent_tasks ?? [];
              const unfinished = agents.filter(
                (t) => t.status === "pending" || t.status === "running",
              ).length;
              if (unfinished > 0) {
                setError(`检测进行中,剩余 ${unfinished} 个维度...`);
              } else {
                setError("检测已完成,LLM 综合研判中...");
              }
            }
          } catch {
            setError("报告正在生成,请稍候...");
          }
        } else {
          setError("加载报告失败");
        }
      })
      .finally(() => setLoading(false));
  }, [projectId, version]);

  useEffect(() => {
    reload();
  }, [reload]);

  // honest-detection-results F3: 拉项目详情判断 identity_info_status
  useEffect(() => {
    if (!projectId) return;
    api
      .getProject(projectId)
      .then((p) => {
        const anyInsufficient = (p.bidders ?? []).some(
          (b) => b.identity_info_status === "insufficient",
        );
        setHasInsufficientIdentity(anyInsufficient);
      })
      .catch(() => {
        /* 失败静默降级:不显示提示 */
      });
  }, [projectId]);

  // 如果 404 且未达重试上限 → 2s 后自动重试
  useEffect(() => {
    if (!error || !error.includes("正在生成") || report !== null) return;
    if (retryCount >= MAX_RETRY) return;
    const t = window.setTimeout(() => {
      setRetryCount((c) => c + 1);
      reload();
    }, RETRY_INTERVAL_MS);
    return () => window.clearTimeout(t);
  }, [error, report, retryCount, reload]);

  const radarData = useMemo(() => {
    if (!report) return [];
    // 固定顺序(和 DIMENSION_LABELS 一致),缺失的维度补 0
    const order = Object.keys(DIMENSION_LABELS);
    const map = new Map(report.dimensions.map((d) => [d.dimension, d]));
    return order.map((dim) => {
      const d = map.get(dim);
      return {
        dimension: DIMENSION_SHORT[dim] ?? dim,
        score: d?.best_score ?? 0,
      };
    });
  }, [report]);

  if (loading) {
    return (
      <div style={{ padding: 48, textAlign: "center" }}>
        <Spin tip="加载报告中..." />
      </div>
    );
  }

  if (error || !report) {
    const generating = error?.includes("正在生成");
    const stillRetrying = generating && retryCount < MAX_RETRY;
    return (
      <div>
        <ReportNavBar
          projectId={projectId ?? ""}
          version={version ?? ""}
          title="检测报告"
          tabKey={null}
        />
        <Card>
          {stillRetrying ? (
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                gap: 12,
                padding: "24px 0",
              }}
            >
              <Spin size="large" />
              <Typography.Text strong style={{ fontSize: 14, color: "#c27c0e" }}>
                AI 综合研判生成中...
              </Typography.Text>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                已等待 {retryCount * 2}s,将自动刷新({Math.max(0, MAX_RETRY - retryCount) * 2}s 内重试)
              </Typography.Text>
            </div>
          ) : (
            <Empty
              description={
                generating
                  ? "报告迟迟未生成,可能后端 LLM 调用失败,请刷新或回到详情页检查"
                  : error || "报告不存在"
              }
            >
              <Space>
                <Button onClick={reload}>刷新</Button>
                <Button onClick={() => navigate(-1)}>返回</Button>
              </Space>
            </Empty>
          )}
        </Card>
      </div>
    );
  }

  const isLlmFallback = report.llm_conclusion.startsWith(LLM_FALLBACK_PREFIX);
  // honest-detection-results: report.risk_level 收紧为 RiskLevel,Record 索引保证非 undefined
  // 删除了 `as RiskLevel` cast 和 `?? RISK_META.low` 运行期兜底
  const risk = RISK_META[report.risk_level];
  const ironcladCount = report.dimensions.filter((d) => d.is_ironclad).length;

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

      {/* Hero:Gauge + Radar 双栏 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col xs={24} md={10}>
          <GaugeCard
            score={report.total_score}
            risk={risk}
            ironcladCount={ironcladCount}
            dimensionsTotal={report.dimensions.length}
          />
        </Col>
        <Col xs={24} md={14}>
          <RadarCard data={radarData} />
        </Col>
      </Row>

      {/* LLM 结论卡 */}
      <Card
        variant="outlined"
        styles={{ body: { padding: 20 } }}
        style={{ marginBottom: 16 }}
      >
        <Typography.Title level={5} style={{ margin: "0 0 12px", fontWeight: 600 }}>
          AI 综合研判
        </Typography.Title>
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
              fontSize: 14,
              color: "#1f2328",
              margin: 0,
              lineHeight: 1.8,
              whiteSpace: "pre-wrap",
              padding: "12px 16px",
              background: "#fafbfc",
              borderLeft: "3px solid #1d4584",
              borderRadius: 4,
            }}
          >
            {report.llm_conclusion}
          </Typography.Paragraph>
        ) : (
          <Typography.Text italic type="secondary">
            AI 综合研判尚未生成
          </Typography.Text>
        )}
      </Card>

      {/* 人工复核 */}
      <Card
        variant="outlined"
        styles={{ body: { padding: 20 } }}
        style={{ marginBottom: 16 }}
      >
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

      {/* 维度得分列表(横向进度条) */}
      <Card
        variant="outlined"
        styles={{ body: { padding: 0 } }}
        title={<span style={{ fontWeight: 600 }}>维度得分</span>}
        extra={
          <Space size={8}>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              共 {report.dimensions.length} 维
            </Typography.Text>
            {ironcladCount > 0 && (
              <Tag color="error" style={{ margin: 0 }}>
                <FireOutlined /> {ironcladCount} 铁证
              </Tag>
            )}
          </Space>
        }
      >
        <div style={{ padding: "8px 0" }}>
          {report.dimensions.map((d) => (
            <DimensionRow
              key={d.dimension}
              dim={d}
              hasInsufficientIdentity={hasInsufficientIdentity}
            />
          ))}
        </div>
      </Card>
    </div>
  );
}

/* ───────── Hero 左:仪表盘 ───────── */
function GaugeCard({
  score,
  risk,
  ironcladCount,
  dimensionsTotal,
}: {
  score: number;
  risk: { label: string; color: string; bg: string };
  ironcladCount: number;
  dimensionsTotal: number;
}) {
  return (
    <Card
      variant="outlined"
      styles={{ body: { padding: 20, display: "flex", flexDirection: "column" } }}
      style={{ height: "100%" }}
    >
      <Typography.Title level={5} style={{ margin: "0 0 4px", fontWeight: 600 }}>
        综合得分
      </Typography.Title>
      <Typography.Text type="secondary" style={{ fontSize: 12, marginBottom: 16 }}>
        基于 {dimensionsTotal} 维度加权合成
      </Typography.Text>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          gap: 24,
          flex: 1,
        }}
      >
        <Progress
          type="dashboard"
          percent={Math.min(100, Math.max(0, score))}
          format={() => (
            <div style={{ lineHeight: 1 }}>
              <div
                style={{
                  fontSize: 28,
                  fontWeight: 700,
                  color: risk.color,
                  letterSpacing: -0.5,
                }}
              >
                {score.toFixed(1)}
              </div>
              <div style={{ fontSize: 11, color: "#8a919d", marginTop: 4 }}>
                / 100
              </div>
            </div>
          )}
          strokeColor={risk.color}
          trailColor="#f0f2f5"
          strokeWidth={10}
          size={180}
        />
      </div>
      <div style={{ textAlign: "center", marginTop: 12 }}>
        <Tag
          style={{
            padding: "4px 16px",
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
        {ironcladCount > 0 && (
          <Tag
            icon={<FireOutlined />}
            color="error"
            style={{ marginLeft: 8, fontWeight: 600 }}
          >
            {ironcladCount} 条铁证
          </Tag>
        )}
      </div>
    </Card>
  );
}

/* ───────── Hero 右:雷达图 ───────── */
function RadarCard({
  data,
}: {
  data: Array<{ dimension: string; score: number }>;
}) {
  const config = {
    data,
    xField: "dimension",
    yField: "score",
    meta: {
      score: { min: 0, max: 100, tickCount: 5 },
    },
    area: {
      style: {
        fill: "#1d4584",
        fillOpacity: 0.14,
      },
    },
    line: {
      style: {
        stroke: "#1d4584",
        strokeWidth: 2,
      },
    },
    point: {
      size: 4,
      shape: "circle",
      style: {
        fill: "#ffffff",
        stroke: "#1d4584",
        strokeWidth: 2,
      },
    },
    axis: {
      y: {
        gridStroke: "#ebedf0",
        gridStrokeWidth: 1,
        labelFontSize: 10,
        labelFill: "#8a919d",
      },
      x: {
        labelFontSize: 12,
        labelFill: "#5c6370",
      },
    },
    tooltip: {
      title: (d: { dimension: string }) => d.dimension,
      items: [
        {
          channel: "y",
          valueFormatter: (v: number) => `${v.toFixed(1)} / 100`,
        },
      ],
    },
    animate: false,
    autoFit: true,
    height: 280,
  };

  return (
    <Card
      variant="outlined"
      styles={{ body: { padding: 20 } }}
      style={{ height: "100%" }}
    >
      <Typography.Title level={5} style={{ margin: "0 0 4px", fontWeight: 600 }}>
        维度风险分布
      </Typography.Title>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        11 个维度的得分雷达;越外圈分数越高,形状越偏哪侧表示该类型风险越突出
      </Typography.Text>
      <div style={{ marginTop: 8 }}>
        <Radar {...config} />
      </div>
    </Card>
  );
}

/* ───────── 维度行(带横向进度条) ───────── */
export function DimensionRow({
  dim: d,
  hasInsufficientIdentity = false,
}: {
  dim: ReportDimension;
  hasInsufficientIdentity?: boolean;
}) {
  const color = scoreColor(d.best_score);
  const counts = d.status_counts;
  // honest-detection-results F3: 对 error_consistency 维度,项目下任一 bidder
  // identity_info 缺失时显示降级提示
  const showIdentityDegraded =
    d.dimension === "error_consistency" && hasInsufficientIdentity;

  return (
    <div
      style={{
        padding: "14px 20px",
        borderBottom: "1px solid #f0f2f5",
        display: "flex",
        flexDirection: "column",
        gap: 10,
        background: d.is_ironclad ? "#fef8f8" : undefined,
        borderLeft: d.is_ironclad ? "3px solid #c53030" : "3px solid transparent",
      }}
    >
     <div
       style={{
         display: "flex",
         alignItems: "center",
         gap: 20,
       }}
     >
      {/* 左:维度名 + 代号 + 铁证 Tag */}
      <div style={{ flex: "0 0 200px", minWidth: 0 }}>
        <Typography.Text strong style={{ fontSize: 14, display: "block" }}>
          {DIMENSION_LABELS[d.dimension] ?? d.dimension}
          {d.is_ironclad && (
            <Tag color="error" style={{ margin: "0 0 0 6px", fontWeight: 600 }}>
              铁证
            </Tag>
          )}
        </Typography.Text>
        <Typography.Text
          type="secondary"
          style={{ fontSize: 11, fontFamily: "monospace" }}
        >
          {d.dimension}
        </Typography.Text>
      </div>

      {/* 中:progress 条 + summary */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <Progress
          percent={Math.min(100, Math.max(0, d.best_score))}
          strokeColor={color}
          trailColor="#f0f2f5"
          format={() => (
            <span style={{ fontSize: 14, fontWeight: 600, color }}>
              {d.best_score.toFixed(1)}
            </span>
          )}
          strokeWidth={10}
        />
        {d.summaries.length > 0 && (
          <Typography.Paragraph
            type="secondary"
            ellipsis={{ rows: 1 }}
            style={{ fontSize: 12, margin: "4px 0 0" }}
          >
            {d.summaries[0]}
          </Typography.Paragraph>
        )}
      </div>

      {/* 右:状态计数 */}
      <div
        style={{
          flex: "0 0 140px",
          display: "flex",
          gap: 10,
          justifyContent: "flex-end",
          fontSize: 11,
          color: "#8a919d",
        }}
      >
        <Tooltip title={`成功 ${counts.succeeded}`}>
          <span>
            <CheckCircleFilled style={{ color: "#2d7a4a", marginRight: 2 }} />
            {counts.succeeded}
          </span>
        </Tooltip>
        <Tooltip title={`跳过 ${counts.skipped}`}>
          <span>
            <MinusCircleFilled style={{ color: "#b1b6bf", marginRight: 2 }} />
            {counts.skipped}
          </span>
        </Tooltip>
        <Tooltip title={`失败 ${counts.failed}`}>
          <span>
            <CloseCircleFilled style={{ color: "#c53030", marginRight: 2 }} />
            {counts.failed}
          </span>
        </Tooltip>
        <Tooltip title={`超时 ${counts.timeout}`}>
          <span>
            <ClockCircleOutlined style={{ color: "#c27c0e", marginRight: 2 }} />
            {counts.timeout}
          </span>
        </Tooltip>
      </div>
     </div>
      {/* honest-detection-results F3: error_consistency 降级提示 */}
      {showIdentityDegraded && (
        <Alert
          type="info"
          showIcon
          icon={<ExclamationCircleOutlined />}
          message="本维度在身份信息缺失情况下已降级判定,结论仅供参考"
          data-testid="dimension-identity-degraded"
          style={{ margin: 0 }}
        />
      )}
    </div>
  );
}

export default ReportPage;
