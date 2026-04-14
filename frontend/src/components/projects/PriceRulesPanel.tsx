/**
 * C5 报价规则面板 (US-4.4 AC-1~4)
 *
 * 替换 C4 PriceRulesPlaceholder。职责:
 * - 展示 LLM 识别的 sheet_name / header_row / column_mapping
 * - 列映射可编辑(code/name/unit/qty/unit_price/total_price 6 列 + skip_cols)
 * - 点"修正并重新应用"→ PUT /api/projects/{pid}/price-rules/{id} → 触发重回填
 * - LLM 仍在识别中(status=identifying)显示 loading
 * - LLM 识别失败(status=failed)显示错误+提示 re-parse
 */
import { useEffect, useState } from "react";

import { api } from "../../services/api";
import type { PriceParsingRule } from "../../types";

interface Props {
  projectId: number;
  /** useParseProgress 里 project_price_rule_ready 事件来时可传自增 key 触发刷新 */
  refreshKey?: number;
}

const MAPPING_KEYS = [
  { key: "code_col", label: "编码列" },
  { key: "name_col", label: "名称列" },
  { key: "unit_col", label: "单位列" },
  { key: "qty_col", label: "数量列" },
  { key: "unit_price_col", label: "单价列" },
  { key: "total_price_col", label: "合价列" },
] as const;

export default function PriceRulesPanel({ projectId, refreshKey }: Props) {
  const [rules, setRules] = useState<PriceParsingRule[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [draft, setDraft] = useState<Record<number, Record<string, string>>>(
    {},
  );
  const [submitMsg, setSubmitMsg] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        setError(null);
        const resp = await api.listPriceRules(projectId);
        if (cancelled) return;
        setRules(resp);
        // 把 server 值拷到本地 draft(以便编辑)
        const d: Record<number, Record<string, string>> = {};
        for (const r of resp) {
          const mapping = (r.column_mapping ?? {}) as Record<string, unknown>;
          d[r.id] = {};
          for (const { key } of MAPPING_KEYS) {
            const v = mapping[key];
            d[r.id][key] = typeof v === "string" ? v : "";
          }
        }
        setDraft(d);
      } catch {
        if (!cancelled) setError("加载失败");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [projectId, refreshKey]);

  if (error)
    return (
      <p role="alert" style={{ color: "#d32f2f" }}>
        {error}
      </p>
    );
  if (rules === null)
    return <p data-testid="price-rules-loading">加载中...</p>;
  if (rules.length === 0)
    return (
      <p
        data-testid="price-rules-empty"
        style={{ color: "#888", fontSize: 13 }}
      >
        等待 LLM 识别报价表结构...
      </p>
    );

  const handleCellChange = (
    ruleId: number,
    key: string,
    value: string,
  ) => {
    setDraft((prev) => ({
      ...prev,
      [ruleId]: { ...(prev[ruleId] ?? {}), [key]: value.toUpperCase() },
    }));
  };

  const handleSubmit = async (rule: PriceParsingRule) => {
    setSubmitting(true);
    setSubmitMsg(null);
    try {
      const merged = {
        ...(rule.column_mapping ?? {}),
        ...draft[rule.id],
      } as Record<string, unknown>;
      await api.putPriceRuleById(projectId, rule.id, {
        sheet_name: rule.sheet_name,
        header_row: rule.header_row,
        column_mapping: merged,
        created_by_llm: false,
        confirmed: true,
      });
      setSubmitMsg("已修正,正在重新回填...");
      // 重新拉列表获取 created_by_llm=false
      const resp = await api.listPriceRules(projectId);
      setRules(resp);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "修正失败";
      setSubmitMsg(msg);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div data-testid="price-rules-panel">
      {rules.map((r) => {
        const status = (r as unknown as { status?: string }).status;
        return (
          <section
            key={r.id}
            style={{ border: "1px solid #e0e0e0", padding: 10, marginBottom: 8 }}
          >
            <header
              style={{
                display: "flex",
                justifyContent: "space-between",
                marginBottom: 6,
              }}
            >
              <strong>
                {r.sheet_name} <small>(表头行 {r.header_row})</small>
              </strong>
              <small>
                {r.created_by_llm ? "LLM 自动" : "人工修正"}
                {" · "}
                {r.confirmed ? "已应用" : "未确认"}
                {status ? ` · ${status}` : ""}
              </small>
            </header>

            <table style={{ fontSize: 13, width: "100%" }}>
              <tbody>
                {MAPPING_KEYS.map(({ key, label }) => (
                  <tr key={key}>
                    <td style={{ padding: 4, width: 100 }}>{label}</td>
                    <td style={{ padding: 4 }}>
                      <input
                        type="text"
                        maxLength={3}
                        style={{ width: 60 }}
                        value={draft[r.id]?.[key] ?? ""}
                        onChange={(e) =>
                          handleCellChange(r.id, key, e.target.value)
                        }
                        aria-label={`修改${label}`}
                        data-testid={`rule-${r.id}-${key}`}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            <button
              type="button"
              onClick={() => void handleSubmit(r)}
              disabled={submitting}
              data-testid={`rule-${r.id}-submit`}
              style={{ marginTop: 6 }}
            >
              修正并重新应用
            </button>
            {submitMsg && (
              <div style={{ marginTop: 4, color: "#555" }} role="status">
                {submitMsg}
              </div>
            )}
          </section>
        );
      })}
    </div>
  );
}
