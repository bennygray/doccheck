/**
 * 文件树 + 解析状态徽章 (US-3.3, C4 file-upload §8.3)。
 *
 * 输入是某 bidder 的 BidDocument 列表;按 source_archive 分组,展示每个归档
 * 下的文件,带状态徽章和错误原因展开。
 */
import { useState } from "react";

import { api } from "../../services/api";
import type { BidDocument, DocumentRole } from "../../types";
import RoleDropdown from "./RoleDropdown";

const STATUS_LABEL: Record<string, string> = {
  pending: "待解析",
  extracting: "解析中",
  extracted: "已解析",
  skipped: "跳过",
  partial: "部分成功",
  failed: "失败",
  needs_password: "需密码",
  // C5 扩展态
  identifying: "识别中",
  identified: "已识别",
  identify_failed: "识别失败",
  pricing: "回填报价",
  priced: "报价完成",
  price_partial: "报价部分成功",
  price_failed: "报价失败",
};
const STATUS_COLOR: Record<string, string> = {
  pending: "#888",
  extracting: "#1677ff",
  extracted: "#52c41a",
  skipped: "#faad14",
  partial: "#faad14",
  failed: "#ff4d4f",
  needs_password: "#722ed1",
  identifying: "#1677ff",
  identified: "#52c41a",
  identify_failed: "#ff4d4f",
  pricing: "#1677ff",
  priced: "#388e3c",
  price_partial: "#faad14",
  price_failed: "#ff4d4f",
};

const FAILURE_STATUSES = new Set([
  "failed",
  "identify_failed",
  "price_failed",
  "skipped",
]);

const ARCHIVE_TYPES = new Set([".zip", ".7z", ".rar"]);

interface Props {
  documents: BidDocument[];
  /** 角色或重试修改后触发父组件刷新(可选) */
  onDocumentChanged?: () => void;
}

export default function FileTree({ documents, onDocumentChanged }: Props) {
  const [openErrors, setOpenErrors] = useState<Record<number, boolean>>({});
  const [retrying, setRetrying] = useState<Record<number, boolean>>({});

  const handleRetry = async (docId: number) => {
    setRetrying((p) => ({ ...p, [docId]: true }));
    try {
      await api.reParseDocument(docId);
      onDocumentChanged?.();
    } catch {
      // 失败提示留给父组件处理或静默
    } finally {
      setRetrying((p) => ({ ...p, [docId]: false }));
    }
  };

  if (documents.length === 0) {
    return (
      <p style={{ color: "#888", padding: 8 }} data-testid="filetree-empty">
        暂无文件。
      </p>
    );
  }

  // 按归档行 vs 子文件分组(source_archive)
  const archives = documents.filter((d) =>
    ARCHIVE_TYPES.has(d.file_type.toLowerCase()),
  );
  const others = documents.filter(
    (d) => !ARCHIVE_TYPES.has(d.file_type.toLowerCase()),
  );

  // 子文件按 source_archive 归属
  const childrenByArchive: Record<string, BidDocument[]> = {};
  for (const f of others) {
    (childrenByArchive[f.source_archive] ??= []).push(f);
  }

  return (
    <div data-testid="filetree" style={{ fontFamily: "monospace", fontSize: 13 }}>
      {archives.map((arc) => (
        <div key={arc.id} style={{ marginBottom: 8 }}>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <span>📦 {arc.file_name}</span>
            <Badge status={arc.parse_status} />
            {arc.parse_error && (
              <button
                type="button"
                onClick={() =>
                  setOpenErrors((p) => ({ ...p, [arc.id]: !p[arc.id] }))
                }
                data-testid={`filetree-error-toggle-${arc.id}`}
                style={{ fontSize: 11, padding: "0 4px" }}
              >
                {openErrors[arc.id] ? "收起" : "查看错误"}
              </button>
            )}
          </div>
          {arc.parse_error && openErrors[arc.id] && (
            <div
              data-testid={`filetree-error-${arc.id}`}
              style={{ color: "#c00", marginLeft: 24, fontSize: 12 }}
            >
              {arc.parse_error}
            </div>
          )}
          <ul style={{ margin: "4px 0 0 24px", padding: 0, listStyle: "none" }}>
            {(childrenByArchive[arc.file_name] ?? []).map((child) => {
              const canEditRole =
                child.file_type === ".docx" || child.file_type === ".xlsx";
              const showRetry = FAILURE_STATUSES.has(child.parse_status);
              return (
                <li
                  key={child.id}
                  style={{
                    display: "flex",
                    gap: 8,
                    alignItems: "center",
                    flexWrap: "wrap",
                  }}
                >
                  <span>📄 {child.file_name}</span>
                  <Badge status={child.parse_status} />
                  {canEditRole && (
                    <RoleDropdown
                      documentId={child.id}
                      role={child.file_role as DocumentRole | null}
                      confidence={child.role_confidence}
                      onChanged={() => onDocumentChanged?.()}
                    />
                  )}
                  {showRetry && (
                    <button
                      type="button"
                      onClick={() => void handleRetry(child.id)}
                      disabled={!!retrying[child.id]}
                      data-testid={`filetree-retry-${child.id}`}
                      style={{ fontSize: 11, padding: "0 6px" }}
                    >
                      {retrying[child.id] ? "重试中..." : "重试"}
                    </button>
                  )}
                  {child.parse_error && (
                    <span style={{ color: "#888", fontSize: 11 }}>
                      {child.parse_error}
                    </span>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </div>
  );
}

function Badge({ status }: { status: string }) {
  return (
    <span
      style={{
        display: "inline-block",
        padding: "0 6px",
        borderRadius: 8,
        background: STATUS_COLOR[status] ?? "#aaa",
        color: "#fff",
        fontSize: 11,
      }}
      data-testid={`status-badge-${status}`}
    >
      {STATUS_LABEL[status] ?? status}
    </span>
  );
}
