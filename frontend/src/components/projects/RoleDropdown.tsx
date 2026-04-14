/**
 * C5 文档角色下拉修改组件 (US-4.3 AC-4~5)
 *
 * - 9 种角色下拉选项
 * - role_confidence='low' 显示黄色"待确认"徽章
 * - 点击修改 → PATCH /api/documents/{id}/role → 成功后触发 onChanged 回调(父组件刷列表)
 */
import { useState } from "react";

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
  const displayLabel =
    role && ROLE_LABELS[role as DocumentRole]
      ? ROLE_LABELS[role as DocumentRole]
      : "未分类";

  const handleChange = async (e: React.ChangeEvent<HTMLSelectElement>) => {
    const next = e.target.value as DocumentRole;
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
      className={isLow ? "role-dropdown role-confidence-low" : "role-dropdown"}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        padding: "2px 6px",
        borderRadius: 4,
        background: isLow ? "#fff8e1" : "#f5f5f5",
        border: isLow ? "1px solid #ffc107" : "1px solid #e0e0e0",
        fontSize: "0.85em",
      }}
    >
      {isLow && (
        <span title="LLM 置信度低,建议确认" style={{ color: "#f57c00" }}>
          待确认
        </span>
      )}
      <select
        value={(role as DocumentRole) || "other"}
        onChange={handleChange}
        disabled={disabled || busy}
        aria-label="修改文档角色"
      >
        {!role && <option value="">{displayLabel}</option>}
        {ROLES.map((r) => (
          <option key={r} value={r}>
            {ROLE_LABELS[r]}
          </option>
        ))}
      </select>
      {error && (
        <span role="alert" style={{ color: "#d32f2f" }}>
          {error}
        </span>
      )}
    </span>
  );
}

export default RoleDropdown;
