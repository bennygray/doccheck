/**
 * 文件树 + 解析状态徽章 (US-3.3, C4 file-upload §8.3)。
 *
 * 输入是某 bidder 的 BidDocument 列表;按 source_archive 分组,展示每个归档
 * 下的文件,带状态徽章和错误原因展开。
 */
import { useState } from "react";
import type { BidDocument } from "../../types";

const STATUS_LABEL: Record<string, string> = {
  pending: "待解析",
  extracting: "解析中",
  extracted: "已解析",
  skipped: "跳过",
  partial: "部分成功",
  failed: "失败",
  needs_password: "需密码",
};
const STATUS_COLOR: Record<string, string> = {
  pending: "#888",
  extracting: "#1677ff",
  extracted: "#52c41a",
  skipped: "#faad14",
  partial: "#faad14",
  failed: "#ff4d4f",
  needs_password: "#722ed1",
};

const ARCHIVE_TYPES = new Set([".zip", ".7z", ".rar"]);

interface Props {
  documents: BidDocument[];
}

export default function FileTree({ documents }: Props) {
  const [openErrors, setOpenErrors] = useState<Record<number, boolean>>({});

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
            {(childrenByArchive[arc.file_name] ?? []).map((child) => (
              <li
                key={child.id}
                style={{ display: "flex", gap: 8, alignItems: "center" }}
              >
                <span>📄 {child.file_path}</span>
                <Badge status={child.parse_status} />
                {child.parse_error && (
                  <span style={{ color: "#888", fontSize: 11 }}>
                    {child.parse_error}
                  </span>
                )}
              </li>
            ))}
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
