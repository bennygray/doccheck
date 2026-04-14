/**
 * 报价列映射规则占位 (US-4.4, C4 file-upload §8.6)。
 *
 * C4 阶段:listPriceRules 拿到的多半是空数组(LLM 在 C5);若有数据(测试 fixture
 * 直接 INSERT 或人工 PUT)则展示表格,否则显示空态文案。
 */
import { useEffect, useState } from "react";
import { api } from "../../services/api";
import type { PriceParsingRule } from "../../types";

interface Props {
  projectId: number;
}

export default function PriceRulesPlaceholder({ projectId }: Props) {
  const [rules, setRules] = useState<PriceParsingRule[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const resp = await api.listPriceRules(projectId);
        if (!cancelled) setRules(resp);
      } catch (err) {
        if (!cancelled) setError("加载失败");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  if (error) {
    return <p style={{ color: "#c00" }}>{error}</p>;
  }
  if (rules === null) {
    return <p data-testid="price-rules-loading">加载中...</p>;
  }
  if (rules.length === 0) {
    return (
      <p
        data-testid="price-rules-empty"
        style={{ color: "#888", fontSize: 13 }}
      >
        等待 LLM 识别报价表后展示(C5 上线后可用)。
      </p>
    );
  }

  return (
    <table
      data-testid="price-rules-table"
      style={{ borderCollapse: "collapse", fontSize: 13, width: "100%" }}
    >
      <thead>
        <tr style={{ background: "#f5f5f5" }}>
          <th style={{ textAlign: "left", padding: 4 }}>Sheet</th>
          <th style={{ textAlign: "left", padding: 4 }}>表头行</th>
          <th style={{ textAlign: "left", padding: 4 }}>来源</th>
          <th style={{ textAlign: "left", padding: 4 }}>已确认</th>
        </tr>
      </thead>
      <tbody>
        {rules.map((r) => (
          <tr key={r.id} style={{ borderTop: "1px solid #eee" }}>
            <td style={{ padding: 4 }}>{r.sheet_name}</td>
            <td style={{ padding: 4 }}>{r.header_row}</td>
            <td style={{ padding: 4 }}>{r.created_by_llm ? "LLM" : "人工"}</td>
            <td style={{ padding: 4 }}>{r.confirmed ? "✓" : "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
