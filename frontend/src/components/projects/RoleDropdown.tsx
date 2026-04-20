/**
 * C5 文档角色下拉修改组件 (US-4.3 AC-4~5)
 *
 * antd 化:Select + Tag(低置信度提示);保留 testid 和业务行为
 */
import { useState } from "react";
import { Select, Tag, Typography } from "antd";

import { api } from "../../services/api";
import type { DocumentRole, RoleConfidence } from "../../types";

const ROLE_LABELS: Record<DocumentRole, string> = {
  technical: "技术方案",
  construction: "施工组织",
  pricing: "报价清单",
  unit_price: "综合单价",
  bid_letter: "投标函",
  qualification: "资质证明",
  company_intro: "企业介绍",
  authorization: "授权委托",
  other: "其他",
};

const ROLES: DocumentRole[] = [
  "technical",
  "construction",
  "pricing",
  "unit_price",
  "bid_letter",
  "qualification",
  "company_intro",
  "authorization",
  "other",
];

export interface RoleDropdownProps {
  documentId: number;
  role: DocumentRole | string | null;
  confidence: RoleConfidence | string | null;
  onChanged?: (newRole: DocumentRole, warn: string | null) => void;
  disabled?: boolean;
}

export function RoleDropdown({
  documentId,
  role,
  confidence,
  onChanged,
  disabled = false,
}: RoleDropdownProps) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isLow = confidence === "low";

  const handleChange = async (next: DocumentRole) => {
    setBusy(true);
    setError(null);
    try {
      const res = await api.patchDocumentRole(documentId, next);
      onChanged?.(next, res.warn);
    } catch (err) {
      setError(err instanceof Error ? err.message : "修改失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <span
      data-testid={`role-dropdown-${documentId}`}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
      }}
    >
      {isLow && (
        <Tag
          color="warning"
          title="LLM 置信度低,建议确认"
          style={{ margin: 0, fontSize: 11 }}
        >
          待确认
        </Tag>
      )}
      <Select
        value={(role as DocumentRole) || undefined}
        onChange={(v) => void handleChange(v as DocumentRole)}
        disabled={disabled || busy}
        size="small"
        aria-label="修改文档角色"
        style={{ width: 120 }}
        placeholder="未分类"
        options={ROLES.map((r) => ({ value: r, label: ROLE_LABELS[r] }))}
      />
      {error && (
        <Typography.Text type="danger" style={{ fontSize: 11 }} role="alert">
          {error}
        </Typography.Text>
      )}
    </span>
  );
}

export default RoleDropdown;
