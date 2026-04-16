/**
 * C16 文本对比页 — pair 级左右双栏对比(US-7.1)
 *
 * - 左右虚拟滚动 + 同步滚动
 * - 相似段落黄色高亮(深浅映射 sim)
 * - hover tooltip(相似度百分比)
 * - 点击高亮段落 → 对侧滚动到匹配段落
 * - 角色切换下拉
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";

import { ApiError, api } from "../../services/api";
import type { TextCompareResponse, TextMatch } from "../../types";

// 相似度 → 背景色(越高越深黄)
function simBgColor(sim: number): string {
  if (sim >= 0.9) return "rgba(234,179,8,0.5)";
  if (sim >= 0.75) return "rgba(234,179,8,0.35)";
  if (sim >= 0.6) return "rgba(234,179,8,0.2)";
  return "rgba(234,179,8,0.1)";
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

  // 段落 index → 该段对应的 matches
  const [leftMatchMap, setLeftMatchMap] = useState<Map<number, TextMatch>>(
    new Map(),
  );
  const [rightMatchMap, setRightMatchMap] = useState<Map<number, TextMatch>>(
    new Map(),
  );

  const leftRef = useRef<HTMLDivElement>(null);
  const rightRef = useRef<HTMLDivElement>(null);
  const syncingRef = useRef(false);

  const fetchData = useCallback(
    (role?: string) => {
      if (!projectId || !bidderA || !bidderB) return;
      setLoading(true);
      api
        .getCompareText(
          projectId,
          bidderA,
          bidderB,
          role || undefined,
          version,
        )
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

  // 同步滚动
  const handleScroll = useCallback(
    (source: "left" | "right") => {
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
    },
    [],
  );

  // 点击高亮 → 对侧滚动到匹配段落
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
      <div className="p-4 text-red-600">
        缺少 bidder_a / bidder_b 参数
      </div>
    );
  }

  if (loading) return <div className="p-4">加载中...</div>;
  if (error) return <div className="p-4 text-red-600">{error}</div>;
  if (!data) return null;

  const hasData =
    data.left_paragraphs.length > 0 || data.right_paragraphs.length > 0;

  return (
    <div className="p-4 max-w-7xl mx-auto">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-xl font-bold">
          文本对比: #{data.bidder_a_id} vs #{data.bidder_b_id}
        </h1>
        {data.available_roles.length > 1 && (
          <select
            className="border rounded px-2 py-1 text-sm"
            value={docRole}
            onChange={(e) => handleRoleChange(e.target.value)}
          >
            {data.available_roles.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        )}
      </div>

      {!hasData ? (
        <div className="text-gray-500 p-8 text-center border rounded">
          无可对比的同类文档
        </div>
      ) : (
        <div className="flex gap-2" style={{ height: "70vh" }}>
          {/* 左栏 */}
          <div
            ref={leftRef}
            className="flex-1 overflow-y-auto border rounded p-2"
            onScroll={() => handleScroll("left")}
            data-testid="left-panel"
          >
            <div className="text-xs text-gray-500 mb-2 font-medium">
              投标人 #{data.bidder_a_id}
            </div>
            {data.left_paragraphs.map((p) => {
              const match = leftMatchMap.get(p.paragraph_index);
              return (
                <div
                  key={p.paragraph_index}
                  data-para-idx={p.paragraph_index}
                  className={`p-1.5 mb-1 rounded text-sm leading-relaxed ${match ? "cursor-pointer" : ""}`}
                  style={
                    match ? { backgroundColor: simBgColor(match.sim) } : {}
                  }
                  title={match ? `相似度: ${(match.sim * 100).toFixed(1)}%` : undefined}
                  onClick={
                    match
                      ? () => scrollToMatch(match.b_idx, "right")
                      : undefined
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
            className="flex-1 overflow-y-auto border rounded p-2"
            onScroll={() => handleScroll("right")}
            data-testid="right-panel"
          >
            <div className="text-xs text-gray-500 mb-2 font-medium">
              投标人 #{data.bidder_b_id}
            </div>
            {data.right_paragraphs.map((p) => {
              const match = rightMatchMap.get(p.paragraph_index);
              return (
                <div
                  key={p.paragraph_index}
                  data-para-idx={p.paragraph_index}
                  className={`p-1.5 mb-1 rounded text-sm leading-relaxed ${match ? "cursor-pointer" : ""}`}
                  style={
                    match ? { backgroundColor: simBgColor(match.sim) } : {}
                  }
                  title={match ? `相似度: ${(match.sim * 100).toFixed(1)}%` : undefined}
                  onClick={
                    match
                      ? () => scrollToMatch(match.a_idx, "left")
                      : undefined
                  }
                >
                  {p.text}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {data.has_more && (
        <div className="mt-2 text-xs text-gray-500">
          显示前 {data.left_paragraphs.length} /
          {data.total_count_left} 段(左)和前{" "}
          {data.right_paragraphs.length} / {data.total_count_right} 段(右)
        </div>
      )}
    </div>
  );
}

export default TextComparePage;
