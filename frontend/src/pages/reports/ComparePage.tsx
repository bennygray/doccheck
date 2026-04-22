/**
 * C15 pair 对比入口页 — C16 扩展 Tab 导航
 *
 * v2 按 **bidder pair 聚合** 视角:
 *  - 每对投标人一张 Card,头部展示总分/风险/命中数
 *  - 卡内列出该 pair 命中的维度(score >= 40 或铁证),每条带"查看证据"链接
 *  - 未命中的 pair 默认折叠成小行,点开才展开
 *  - 支持"只看命中的对"开关
 *  - 3-5 家场景(3~10 对)默认按总分 desc 排序,风险一目了然
 */
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  Card,
  Collapse,
  Empty,
  Space,
  Spin,
  Switch,
  Tag,
  Typography,
} from "antd";
import { FireOutlined, RightOutlined } from "@ant-design/icons";

import CompareSubTabs from "../../components/reports/CompareSubTabs";
import ReportNavBar from "../../components/reports/ReportNavBar";
import { ApiError, api } from "../../services/api";
import type { PairComparisonItem } from "../../types";
import { summarizeEvidence } from "../../utils/evidenceSummary";

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

/** 维度→证据链接 */
function evidenceHref(
  projectId: string,
  version: string,
  dim: string,
  a: number,
  b: number,
): string | null {
  const base = `/reports/${projectId}/${version}/compare`;
  if (dim === "text_similarity" || dim === "section_similarity") {
    return `${base}/text?bidder_a=${a}&bidder_b=${b}`;
  }
  if (dim === "price_consistency" || dim === "price_anomaly") {
    return `${base}/price`;
  }
  if (dim.startsWith("metadata_")) return `${base}/metadata`;
  return null;
}

const HIT_THRESHOLD = 40;

interface PairGroup {
  bidder_a_id: number;
  bidder_b_id: number;
  items: PairComparisonItem[];
  maxScore: number;
  ironcladCount: number;
  hits: PairComparisonItem[];
  misses: PairComparisonItem[];
}

export function ComparePage() {
  const { projectId, version } = useParams<{
    projectId: string;
    version: string;
  }>();
  const [items, setItems] = useState<PairComparisonItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // 3-5 家投标人时默认开启,避免一屏都是低分 pair
  const [onlyHits, setOnlyHits] = useState(true);

  useEffect(() => {
    if (!projectId || !version) return;
    setLoading(true);
    api
      // 上限提到 500:10 家 = 45 对 × 11 维度 = 495 行
      .getReportPairs(projectId, version, "score_desc", 500)
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

  /** 按 bidder pair 聚合,每组按分数 desc 排;组间按 maxScore desc 排 */
  const pairs: PairGroup[] = useMemo(() => {
    const map = new Map<string, PairGroup>();
    for (const it of items) {
      // 统一 pair key:小 id 在前,避免顺序不一致导致分组重复
      const [a, b] =
        it.bidder_a_id <= it.bidder_b_id
          ? [it.bidder_a_id, it.bidder_b_id]
          : [it.bidder_b_id, it.bidder_a_id];
      const key = `${a}-${b}`;
      if (!map.has(key)) {
        map.set(key, {
          bidder_a_id: a,
          bidder_b_id: b,
          items: [],
          maxScore: 0,
          ironcladCount: 0,
          hits: [],
          misses: [],
        });
      }
      const grp = map.get(key)!;
      grp.items.push(it);
      if (it.score > grp.maxScore) grp.maxScore = it.score;
      if (it.is_ironclad) grp.ironcladCount += 1;
    }
    // 每组内:hits 按 score desc,misses 降序便于折叠展示
    for (const g of map.values()) {
      g.items.sort((a, b) => b.score - a.score);
      g.hits = g.items.filter((i) => i.is_ironclad || i.score >= HIT_THRESHOLD);
      g.misses = g.items.filter(
        (i) => !i.is_ironclad && i.score < HIT_THRESHOLD,
      );
    }
    return [...map.values()].sort((a, b) => {
      // 先按铁证数,再按最大分
      if (a.ironcladCount !== b.ironcladCount)
        return b.ironcladCount - a.ironcladCount;
      return b.maxScore - a.maxScore;
    });
  }, [items]);

  const displayed = onlyHits ? pairs.filter((p) => p.hits.length > 0) : pairs;
  const hiddenCount = pairs.length - displayed.length;

  return (
    <div>
      <ReportNavBar
        projectId={projectId ?? ""}
        version={version ?? ""}
        title="投标人对比"
        subtitle={
          pairs.length > 0
            ? `共 ${pairs.length} 对投标人,其中 ${pairs.filter((p) => p.hits.length > 0).length} 对存在维度命中`
            : "按维度 × 投标人对的命中评分"
        }
        tabKey="compare"
      />

      <Card variant="outlined" styles={{ body: { padding: 0 } }}>
        <CompareSubTabs
          projectId={projectId ?? ""}
          version={version ?? ""}
          activeKey="overview"
          extra={
            /* 只有多于 1 对时,过滤开关才有意义 */
            pairs.length > 1 ? (
              <Space size={8}>
                <Typography.Text style={{ fontSize: 12, color: "#5c6370" }}>
                  只看命中的对
                </Typography.Text>
                <Switch
                  size="small"
                  checked={onlyHits}
                  onChange={setOnlyHits}
                />
              </Space>
            ) : null
          }
        />

        {loading ? (
          <div style={{ padding: 48, textAlign: "center" }}>
            <Spin tip="加载中..." />
          </div>
        ) : error ? (
          <div style={{ padding: 32 }}>
            <Empty
              description={<span style={{ color: "#c53030" }}>{error}</span>}
            />
          </div>
        ) : pairs.length === 0 ? (
          <div style={{ padding: 32 }}>
            <Empty description="无对比数据" />
          </div>
        ) : (
          <div style={{ padding: 16 }}>
            <Space direction="vertical" size={12} style={{ width: "100%" }}>
              {displayed.map((g) => (
                <PairCard
                  key={`${g.bidder_a_id}-${g.bidder_b_id}`}
                  group={g}
                  projectId={projectId!}
                  version={version!}
                />
              ))}
              {hiddenCount > 0 && (
                <Typography.Text
                  type="secondary"
                  style={{
                    fontSize: 12,
                    textAlign: "center",
                    display: "block",
                    padding: "8px 0",
                  }}
                >
                  已隐藏 {hiddenCount} 对无命中的投标人对 · 关闭开关查看全部
                </Typography.Text>
              )}
            </Space>
          </div>
        )}
      </Card>
    </div>
  );
}

/* ───────── pair 聚合卡 ───────── */

function PairCard({
  group,
  projectId,
  version,
}: {
  group: PairGroup;
  projectId: string;
  version: string;
}) {
  const { bidder_a_id, bidder_b_id, hits, misses, maxScore, ironcladCount } =
    group;
  const hasHit = hits.length > 0;
  const tierColor =
    ironcladCount > 0 || maxScore >= 70
      ? "#c53030"
      : maxScore >= 40
        ? "#c27c0e"
        : "#8a919d";

  return (
    <Card
      variant="outlined"
      styles={{ body: { padding: 0 } }}
      style={{
        borderLeft: ironcladCount > 0 ? "3px solid #c53030" : undefined,
      }}
    >
      {/* pair 头:投标人 pair + 最高分 + 铁证数 */}
      <div
        style={{
          padding: "14px 20px",
          borderBottom: hasHit ? "1px solid #f0f2f5" : undefined,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: 12,
          flexWrap: "wrap",
          background: ironcladCount > 0 ? "#fef8f8" : "#fafbfc",
        }}
      >
        <Space size={10} align="center">
          <BidderBadge id={bidder_a_id} />
          <span style={{ color: "#8a919d", fontWeight: 500 }}>×</span>
          <BidderBadge id={bidder_b_id} />
          {ironcladCount > 0 && (
            <Tag color="error" style={{ margin: 0, fontWeight: 600 }}>
              <FireOutlined /> {ironcladCount} 铁证
            </Tag>
          )}
        </Space>
        <Space size={10} align="center">
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {hits.length} / {group.items.length} 维度命中
          </Typography.Text>
          <Typography.Text
            strong
            style={{ fontSize: 20, color: tierColor, minWidth: 48, textAlign: "right" }}
          >
            {maxScore.toFixed(1)}
          </Typography.Text>
        </Space>
      </div>

      {/* 命中维度列表 */}
      {hasHit && (
        <div>
          {hits.map((it) => (
            <DimensionHitRow
              key={it.id}
              item={it}
              projectId={projectId}
              version={version}
            />
          ))}
        </div>
      )}

      {/* 未命中维度折叠 */}
      {misses.length > 0 && (
        <Collapse
          ghost
          items={[
            {
              key: "misses",
              label: (
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  未命中 {misses.length} 维度
                </Typography.Text>
              ),
              children: (
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns:
                      "repeat(auto-fill, minmax(180px, 1fr))",
                    gap: 4,
                    padding: "0 12px 12px",
                  }}
                >
                  {misses.map((m) => (
                    <div
                      key={m.id}
                      style={{
                        fontSize: 12,
                        color: "#8a919d",
                        padding: "4px 8px",
                        display: "flex",
                        justifyContent: "space-between",
                      }}
                    >
                      <span>
                        {DIMENSION_LABELS[m.dimension] ?? m.dimension}
                      </span>
                      <span>{m.score.toFixed(1)}</span>
                    </div>
                  ))}
                </div>
              ),
            },
          ]}
        />
      )}

      {!hasHit && (
        <div
          style={{
            padding: "10px 20px",
            fontSize: 12,
            color: "#8a919d",
          }}
        >
          此对无维度命中
        </div>
      )}
    </Card>
  );
}

function DimensionHitRow({
  item,
  projectId,
  version,
}: {
  item: PairComparisonItem;
  projectId: string;
  version: string;
}) {
  const [showRaw, setShowRaw] = useState(false);
  const href = evidenceHref(
    projectId,
    version,
    item.dimension,
    item.bidder_a_id,
    item.bidder_b_id,
  );
  const scoreColor =
    item.score >= 70 ? "#c53030" : item.score >= 40 ? "#c27c0e" : "#5c6370";
  const summary = summarizeEvidence(item.dimension, item.evidence_summary);
  /* 只有"原始是 JSON 且被翻译"时才允许展开原始;否则就是展示 summary 本身,没必要展开 */
  const hasRawJson =
    !!item.evidence_summary &&
    item.evidence_summary.trim().startsWith("{") &&
    summary !== item.evidence_summary;

  return (
    <div style={{ borderBottom: "1px solid #f0f2f5" }}>
      <div
        style={{
          padding: "10px 20px",
          display: "flex",
          alignItems: "center",
          gap: 12,
        }}
      >
        <div style={{ flex: "0 0 140px", minWidth: 0 }}>
          <Typography.Text strong style={{ fontSize: 13 }}>
            {DIMENSION_LABELS[item.dimension] ?? item.dimension}
          </Typography.Text>
          {item.is_ironclad && (
            <Tag color="error" style={{ margin: "0 0 0 6px", fontWeight: 600 }}>
              铁证
            </Tag>
          )}
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          {summary ? (
            <Typography.Text
              style={{ fontSize: 13, color: "#2c3139", display: "block" }}
              ellipsis={{ tooltip: summary }}
            >
              {summary}
            </Typography.Text>
          ) : (
            <span style={{ color: "#b1b6bf", fontSize: 12 }}>—</span>
          )}
        </div>
        <Typography.Text
          strong
          style={{
            fontSize: 15,
            color: scoreColor,
            flex: "0 0 50px",
            textAlign: "right",
          }}
        >
          {item.score.toFixed(1)}
        </Typography.Text>
        <Space size={10} style={{ flex: "0 0 auto" }}>
          {hasRawJson && (
            <Typography.Link
              onClick={() => setShowRaw((s) => !s)}
              style={{ fontSize: 12, color: "#8a919d" }}
            >
              {showRaw ? "收起" : "原文"}
            </Typography.Link>
          )}
          {href ? (
            <Link to={href}>
              <Typography.Text
                style={{ color: "#1d4584", fontSize: 12, whiteSpace: "nowrap" }}
              >
                查看证据 <RightOutlined style={{ fontSize: 9 }} />
              </Typography.Text>
            </Link>
          ) : (
            <span style={{ width: 64, display: "inline-block" }} />
          )}
        </Space>
      </div>
      {showRaw && item.evidence_summary && (
        <pre
          style={{
            margin: 0,
            padding: "8px 20px 12px 160px",
            fontSize: 11.5,
            lineHeight: 1.55,
            color: "#5c6370",
            background: "#fafbfc",
            whiteSpace: "pre-wrap",
            wordBreak: "break-all",
            fontFamily:
              "ui-monospace, 'SF Mono', Menlo, Consolas, monospace",
          }}
        >
          {prettifyJson(item.evidence_summary)}
        </pre>
      )}
    </div>
  );
}

function prettifyJson(raw: string): string {
  try {
    return JSON.stringify(JSON.parse(raw), null, 2);
  } catch {
    return raw;
  }
}

function BidderBadge({ id }: { id: number }) {
  return (
    <Typography.Text strong style={{ fontSize: 14 }}>
      <span style={{ color: "#5c6370", fontSize: 12, marginRight: 4 }}>#</span>
      {id}
    </Typography.Text>
  );
}

export default ComparePage;
