/**
 * C5 报价规则面板 (US-4.4 AC-1~4)
 *
 * 展示 LLM 识别的 sheet_name / header_row / column_mapping;列映射可编辑,
 * 修正后 PUT /api/projects/{pid}/price-rules/{id} 触发重回填。
 *
 * antd 化:Card + Table(描述布局)+ Input + Button;data-testid 保留
 */
import { useEffect, useState } from "react";
import { Alert, Button, Card, Empty, Input, Space, Tag, Typography } from "antd";

import { api } from "../../services/api";
import type { PriceParsingRule } from "../../types";

interface Props {
  projectId: number;
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
  const [draft, setDraft] = useState<Record<number, Record<string, string>>>({});
  const [submitMsg, setSubmitMsg] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        setError(null);
        const resp = await api.listPriceRules(projectId);
        if (cancelled) return;
        setRules(resp);
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
      <Alert type="error" role="alert" message={error} showIcon />
    );
  if (rules === null)
    return (
      <Typography.Text data-testid="price-rules-loading" type="secondary">
        加载中...
      </Typography.Text>
    );
  if (rules.length === 0)
    return (
      <Empty
        data-testid="price-rules-empty"
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description={
          <div
            style={{
              color: "#8a919d",
              fontSize: 13,
              lineHeight: 1.7,
              maxWidth: 420,
              margin: "0 auto",
            }}
          >
            <div style={{ fontWeight: 500, color: "#5c6370", marginBottom: 4 }}>
              暂无报价规则
            </div>
            <div>
              系统仅对角色为<b>「报价」</b>的 <b>.xlsx</b> 文件自动识别表结构。
              当前投标人的报价文件若为 .docx/.pdf,请转成 .xlsx 重新上传,
              或手工录入规则。
            </div>
          </div>
        }
        style={{ padding: "20px 0" }}
      />
    );

  const handleCellChange = (ruleId: number, key: string, value: string) => {
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
      <Space direction="vertical" size={12} style={{ width: "100%" }}>
        {rules.map((r) => {
          const status = (r as unknown as { status?: string }).status;
          return (
            <Card
              key={r.id}
              size="small"
              variant="outlined"
              styles={{ body: { padding: 14 } }}
            >
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  marginBottom: 10,
                  flexWrap: "wrap",
                  gap: 8,
                }}
              >
                <Space size={8}>
                  <Typography.Text strong style={{ fontSize: 14 }}>
                    {r.sheet_name}
                  </Typography.Text>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    表头行 {r.header_row}
                  </Typography.Text>
                </Space>
                <Space size={4}>
                  <Tag
                    color={r.created_by_llm ? "blue" : "default"}
                    style={{ margin: 0 }}
                  >
                    {r.created_by_llm ? "LLM 自动" : "人工修正"}
                  </Tag>
                  <Tag
                    color={r.confirmed ? "success" : "warning"}
                    style={{ margin: 0 }}
                  >
                    {r.confirmed ? "已应用" : "未确认"}
                  </Tag>
                  {status ? (
                    <Tag style={{ margin: 0 }}>{status}</Tag>
                  ) : null}
                </Space>
              </div>

              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))",
                  gap: 10,
                  marginBottom: 10,
                }}
              >
                {MAPPING_KEYS.map(({ key, label }) => (
                  <div key={key}>
                    <Typography.Text
                      type="secondary"
                      style={{
                        fontSize: 12,
                        display: "block",
                        marginBottom: 4,
                      }}
                    >
                      {label}
                    </Typography.Text>
                    <Input
                      size="small"
                      maxLength={3}
                      value={draft[r.id]?.[key] ?? ""}
                      onChange={(e) =>
                        handleCellChange(r.id, key, e.target.value)
                      }
                      aria-label={`修改${label}`}
                      data-testid={`rule-${r.id}-${key}`}
                      style={{ width: 80 }}
                      placeholder="A"
                    />
                  </div>
                ))}
              </div>

              <Space size={12}>
                <Button
                  size="small"
                  type="primary"
                  onClick={() => void handleSubmit(r)}
                  loading={submitting}
                  data-testid={`rule-${r.id}-submit`}
                >
                  修正并重新应用
                </Button>
                {submitMsg && (
                  <Typography.Text type="secondary" style={{ fontSize: 12 }} role="status">
                    {submitMsg}
                  </Typography.Text>
                )}
              </Space>
            </Card>
          );
        })}
      </Space>
    </div>
  );
}
