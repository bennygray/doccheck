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
import { useParams, useSearchParams } from "react-router-dom";
import { Card, Empty, Select, Spin, Typography } from "antd";

import CompareSubTabs from "../../components/reports/CompareSubTabs";
import ReportNavBar from "../../components/reports/ReportNavBar";
import { ApiError, api } from "../../services/api";
import type { TextCompareResponse, TextMatch } from "../../types";

// 相似度 → 背景色(越高越深琥珀)
function simBgColor(sim: number): string {
  if (sim >= 0.9) return "rgba(194, 124, 14, 0.38)";
  if (sim >= 0.75) return "rgba(194, 124, 14, 0.26)";
  if (sim >= 0.6) return "rgba(194, 124, 14, 0.16)";
  return "rgba(194, 124, 14, 0.08)";
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
          <Empty
            description={
              <span style={{ color: "#c53030" }}>缺少 bidder_a / bidder_b 参数</span>
            }
          />
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
                  return (
                    <div
                      key={p.paragraph_index}
                      data-para-idx={p.paragraph_index}
                      style={{
                        padding: "6px 8px",
                        marginBottom: 4,
                        borderRadius: 4,
                        fontSize: 13,
                        lineHeight: 1.7,
                        cursor: match ? "pointer" : "default",
                        backgroundColor: match ? simBgColor(match.sim) : undefined,
                        color: "#1f2328",
                      }}
                      title={
                        match
                          ? `相似度: ${(match.sim * 100).toFixed(1)}%`
                          : undefined
                      }
                      onClick={
                        match ? () => scrollToMatch(match.b_idx, "right") : undefined
                      }
                    >
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
                  return (
                    <div
                      key={p.paragraph_index}
                      data-para-idx={p.paragraph_index}
                      style={{
                        padding: "6px 8px",
                        marginBottom: 4,
                        borderRadius: 4,
                        fontSize: 13,
                        lineHeight: 1.7,
                        cursor: match ? "pointer" : "default",
                        backgroundColor: match ? simBgColor(match.sim) : undefined,
                        color: "#1f2328",
                      }}
                      title={
                        match
                          ? `相似度: ${(match.sim * 100).toFixed(1)}%`
                          : undefined
                      }
                      onClick={
                        match ? () => scrollToMatch(match.a_idx, "left") : undefined
                      }
                    >
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
