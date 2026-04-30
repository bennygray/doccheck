/**
 * C16 文本对比页 — pair 级左右双栏对比(US-7.1)
 *
 * - 左右虚拟滚动 + 同步滚动
 * - 相似段落黄色高亮(深浅映射 sim)
 * - hover tooltip(相似度百分比)
 * - 点击高亮段落 → 对侧滚动到匹配段落
 * - 角色切换下拉
 *
 * data-testid 保留:left-panel / right-panel
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { Button, Card, Empty, Select, Space, Spin, Typography } from "antd";

import CompareSubTabs from "../../components/reports/CompareSubTabs";
import ReportNavBar from "../../components/reports/ReportNavBar";
import { ApiError, api } from "../../services/api";
import { colors } from "../../theme/tokens";
import type { TextCompareResponse, TextMatch } from "../../types";
import { isTenderBaselineEnabled } from "../../utils/featureFlags";

// 相似度 → 背景色(越高越深琥珀)
function simBgColor(sim: number): string {
  if (sim >= 0.9) return "rgba(194, 124, 14, 0.38)";
  if (sim >= 0.75) return "rgba(194, 124, 14, 0.26)";
  if (sim >= 0.6) return "rgba(194, 124, 14, 0.16)";
  return "rgba(194, 124, 14, 0.08)";
}

// detect-tender-baseline §7.12:模板段灰底优先级高于 simBgColor
function paragraphBgColor(
  match: TextMatch | undefined,
  baselineEnabled: boolean,
): string | undefined {
  if (!match) return undefined;
  if (baselineEnabled && match.baseline_matched) return colors.bgTemplate;
  return simBgColor(match.sim);
}

function BaselineTag({ source }: { source: NonNullable<TextMatch["baseline_source"]> }) {
  const label =
    source === "tender" ? "L1 招标" : source === "consensus" ? "L2 共识" : "模板";
  const fg =
    source === "tender"
      ? colors.primary
      : source === "consensus"
        ? colors.warning
        : colors.textTertiary;
  return (
    <span
      data-testid={`baseline-tag-${source}`}
      style={{
        display: "inline-block",
        fontSize: 10,
        fontWeight: 500,
        color: fg,
        border: `1px solid ${fg}`,
        borderRadius: 3,
        padding: "0 4px",
        marginRight: 6,
        verticalAlign: "middle",
        lineHeight: "16px",
      }}
    >
      {label}
    </span>
  );
}

export function TextComparePage() {
  const { projectId, version } = useParams<{
    projectId: string;
    version: string;
  }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const bidderA = Number(searchParams.get("bidder_a") || 0);
  const bidderB = Number(searchParams.get("bidder_b") || 0);
  const [docRole, setDocRole] = useState(searchParams.get("doc_role") || "");

  const [data, setData] = useState<TextCompareResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // 无 bidder 参数时,自动从 pair 列表挑第一个 text_similarity pair
  const [autoResolving, setAutoResolving] = useState(false);
  const [noPairsFallback, setNoPairsFallback] = useState(false);

  useEffect(() => {
    if (bidderA && bidderB) return;
    if (!projectId || !version) return;
    setAutoResolving(true);
    api
      .getReportPairs(projectId, version, "score_desc", 100)
      .then((r) => {
        const firstTextPair = r.items.find(
          (it) => it.dimension === "text_similarity" && it.score > 0,
        );
        if (firstTextPair) {
          const next = new URLSearchParams(searchParams);
          next.set("bidder_a", String(firstTextPair.bidder_a_id));
          next.set("bidder_b", String(firstTextPair.bidder_b_id));
          setSearchParams(next, { replace: true });
        } else {
          setNoPairsFallback(true);
        }
      })
      .catch(() => setNoPairsFallback(true))
      .finally(() => setAutoResolving(false));
  }, [bidderA, bidderB, projectId, version, searchParams, setSearchParams]);

  const [leftMatchMap, setLeftMatchMap] = useState<Map<number, TextMatch>>(new Map());
  const [rightMatchMap, setRightMatchMap] = useState<Map<number, TextMatch>>(new Map());

  const leftRef = useRef<HTMLDivElement>(null);
  const rightRef = useRef<HTMLDivElement>(null);
  const syncingRef = useRef(false);

  const fetchData = useCallback(
    (role?: string) => {
      if (!projectId || !bidderA || !bidderB) return;
      setLoading(true);
      api
        .getCompareText(projectId, bidderA, bidderB, role || undefined, version)
        .then((r) => {
          setData(r);
          setDocRole(r.doc_role);
          setError(null);

          const lm = new Map<number, TextMatch>();
          const rm = new Map<number, TextMatch>();
          for (const m of r.matches) {
            lm.set(m.a_idx, m);
            rm.set(m.b_idx, m);
          }
          setLeftMatchMap(lm);
          setRightMatchMap(rm);
        })
        .catch((err) => {
          setError(
            err instanceof ApiError ? `加载失败 (${err.status})` : "加载失败",
          );
        })
        .finally(() => setLoading(false));
    },
    [projectId, bidderA, bidderB, version],
  );

  useEffect(() => {
    fetchData(docRole);
  }, [fetchData, docRole]);

  const handleScroll = useCallback((source: "left" | "right") => {
    if (syncingRef.current) return;
    syncingRef.current = true;
    const from = source === "left" ? leftRef.current : rightRef.current;
    const to = source === "left" ? rightRef.current : leftRef.current;
    if (from && to) {
      to.scrollTop = from.scrollTop;
    }
    requestAnimationFrame(() => {
      syncingRef.current = false;
    });
  }, []);

  const scrollToMatch = useCallback(
    (targetIdx: number, side: "left" | "right") => {
      const container = side === "left" ? leftRef.current : rightRef.current;
      if (!container) return;
      const el = container.querySelector(`[data-para-idx="${targetIdx}"]`);
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "center" });
      }
    },
    [],
  );

  const handleRoleChange = (role: string) => {
    setDocRole(role);
    const params = new URLSearchParams(searchParams);
    params.set("doc_role", role);
    setSearchParams(params, { replace: true });
  };

  if (!bidderA || !bidderB) {
    return (
      <div>
        <ReportNavBar
          projectId={projectId ?? ""}
          version={version ?? ""}
          title="文本对比"
          tabKey="compare"
        />
        <Card>
          {autoResolving ? (
            <div style={{ padding: 48, textAlign: "center" }}>
              <Spin tip="正在自动选择一对投标人..." />
            </div>
          ) : noPairsFallback ? (
            <Empty
              description={
                <Space direction="vertical" size={8} align="center">
                  <span style={{ color: "#5c6370" }}>
                    暂无可对比的文本相似投标人对
                  </span>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    请在"对比总览"选择一对投标人,或等待检测完成
                  </Typography.Text>
                </Space>
              }
            >
              <Link to={`/reports/${projectId}/${version}/compare`}>
                <Button type="primary">去对比总览</Button>
              </Link>
            </Empty>
          ) : (
            <div style={{ padding: 48, textAlign: "center" }}>
              <Spin tip="加载中..." />
            </div>
          )}
        </Card>
      </div>
    );
  }

  if (loading) {
    return (
      <div>
        <ReportNavBar
          projectId={projectId ?? ""}
          version={version ?? ""}
          title="文本对比"
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
          title="文本对比"
          tabKey="compare"
        />
        <Card>
          <Empty description={<span style={{ color: "#c53030" }}>{error}</span>} />
        </Card>
      </div>
    );
  }

  if (!data) return null;

  const hasData =
    data.left_paragraphs.length > 0 || data.right_paragraphs.length > 0;
  const baselineEnabled = isTenderBaselineEnabled();

  const roleExtra =
    data.available_roles.length > 1 ? (
      <Select
        value={docRole}
        onChange={handleRoleChange}
        style={{ width: 160 }}
        size="small"
        options={data.available_roles.map((r) => ({ value: r, label: r }))}
      />
    ) : null;

  return (
    <div>
      <ReportNavBar
        projectId={projectId!}
        version={version!}
        title={`文本对比: #${data.bidder_a_id} vs #${data.bidder_b_id}`}
        subtitle="段落级双栏同步滚动,高亮色越深相似度越高;点击高亮段落跳转至对侧匹配位置"
        tabKey="compare"
      />

      <Card variant="outlined" styles={{ body: { padding: 0 } }}>
        <CompareSubTabs
          projectId={projectId!}
          version={version!}
          activeKey="text"
          extra={roleExtra}
        />

        {!hasData ? (
          <div style={{ padding: 32 }}>
            <Empty description="无可对比的同类文档" />
          </div>
        ) : (
          <>
            {/* 极简相似度图例:告诉用户颜色深浅的含义,避免猜色 */}
            <div
              style={{
                padding: "10px 20px",
                borderBottom: "1px solid #f0f2f5",
                display: "flex",
                alignItems: "center",
                gap: 14,
                flexWrap: "wrap",
                fontSize: 12,
                color: "#5c6370",
              }}
            >
              <span>相似度</span>
              {[
                { label: "≥ 90%", bg: simBgColor(0.95) },
                { label: "75~90%", bg: simBgColor(0.8) },
                { label: "60~75%", bg: simBgColor(0.65) },
                { label: "< 60%", bg: simBgColor(0.5) },
              ].map((s) => (
                <span
                  key={s.label}
                  style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
                >
                  <span
                    style={{
                      display: "inline-block",
                      width: 14,
                      height: 10,
                      borderRadius: 2,
                      background: s.bg,
                      border: "1px solid #ebedf0",
                    }}
                  />
                  {s.label}
                </span>
              ))}
              <span style={{ marginLeft: "auto", color: "#8a919d" }}>
                点击高亮段落可跳转至对侧匹配位置
              </span>
            </div>
            <div
              style={{
                display: "flex",
                gap: 12,
                height: "68vh",
                padding: 16,
              }}
            >
              {/* 左栏 */}
              <div
                ref={leftRef}
                onScroll={() => handleScroll("left")}
                data-testid="left-panel"
                style={{
                  flex: 1,
                  overflowY: "auto",
                  border: "1px solid #e4e7ed",
                  borderRadius: 8,
                  padding: 12,
                  background: "#ffffff",
                }}
              >
                <Typography.Text
                  type="secondary"
                  style={{
                    fontSize: 12,
                    fontWeight: 500,
                    marginBottom: 8,
                    display: "block",
                  }}
                >
                  投标人 #{data.bidder_a_id}
                </Typography.Text>
                {data.left_paragraphs.map((p) => {
                  const match = leftMatchMap.get(p.paragraph_index);
                  const isBaselineHit =
                    baselineEnabled && match?.baseline_matched === true;
                  return (
                    <div
                      key={p.paragraph_index}
                      data-para-idx={p.paragraph_index}
                      data-baseline-matched={isBaselineHit ? "true" : undefined}
                      style={{
                        padding: "6px 8px",
                        marginBottom: 4,
                        borderRadius: 4,
                        fontSize: 13,
                        lineHeight: 1.7,
                        cursor: match ? "pointer" : "default",
                        backgroundColor: paragraphBgColor(match, baselineEnabled),
                        color: isBaselineHit ? "#5c6370" : "#1f2328",
                      }}
                      title={
                        isBaselineHit
                          ? `模板段(${match?.baseline_source ?? "none"})— 已剔除铁证`
                          : match
                            ? `相似度: ${(match.sim * 100).toFixed(1)}%`
                            : undefined
                      }
                      onClick={
                        match ? () => scrollToMatch(match.b_idx, "right") : undefined
                      }
                    >
                      {isBaselineHit && match?.baseline_source && (
                        <BaselineTag source={match.baseline_source} />
                      )}
                      {p.text}
                    </div>
                  );
                })}
              </div>

              {/* 右栏 */}
              <div
                ref={rightRef}
                onScroll={() => handleScroll("right")}
                data-testid="right-panel"
                style={{
                  flex: 1,
                  overflowY: "auto",
                  border: "1px solid #e4e7ed",
                  borderRadius: 8,
                  padding: 12,
                  background: "#ffffff",
                }}
              >
                <Typography.Text
                  type="secondary"
                  style={{
                    fontSize: 12,
                    fontWeight: 500,
                    marginBottom: 8,
                    display: "block",
                  }}
                >
                  投标人 #{data.bidder_b_id}
                </Typography.Text>
                {data.right_paragraphs.map((p) => {
                  const match = rightMatchMap.get(p.paragraph_index);
                  const isBaselineHit =
                    baselineEnabled && match?.baseline_matched === true;
                  return (
                    <div
                      key={p.paragraph_index}
                      data-para-idx={p.paragraph_index}
                      data-baseline-matched={isBaselineHit ? "true" : undefined}
                      style={{
                        padding: "6px 8px",
                        marginBottom: 4,
                        borderRadius: 4,
                        fontSize: 13,
                        lineHeight: 1.7,
                        cursor: match ? "pointer" : "default",
                        backgroundColor: paragraphBgColor(match, baselineEnabled),
                        color: isBaselineHit ? "#5c6370" : "#1f2328",
                      }}
                      title={
                        isBaselineHit
                          ? `模板段(${match?.baseline_source ?? "none"})— 已剔除铁证`
                          : match
                            ? `相似度: ${(match.sim * 100).toFixed(1)}%`
                            : undefined
                      }
                      onClick={
                        match ? () => scrollToMatch(match.a_idx, "left") : undefined
                      }
                    >
                      {isBaselineHit && match?.baseline_source && (
                        <BaselineTag source={match.baseline_source} />
                      )}
                      {p.text}
                    </div>
                  );
                })}
              </div>
            </div>

            {data.has_more && (
              <div
                style={{
                  padding: "8px 20px",
                  fontSize: 11.5,
                  color: "#8a919d",
                  borderTop: "1px solid #f0f2f5",
                  background: "#fafbfc",
                }}
              >
                显示前 {data.left_paragraphs.length} / {data.total_count_left} 段(左)
                和前 {data.right_paragraphs.length} / {data.total_count_right} 段(右)
              </div>
            )}
          </>
        )}
      </Card>
    </div>
  );
}

export default TextComparePage;
