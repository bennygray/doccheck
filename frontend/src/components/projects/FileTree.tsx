/**
 * 文件树 + 解析状态徽章 (US-3.3, C4 file-upload §8.3)。
 *
 * antd 化:antd Tag 状态 + Button 重试/查看错误;保留所有 data-testid
 */
import { useState } from "react";
import { Button, Space, Tag, Typography } from "antd";
import {
  FileOutlined,
  FolderOpenOutlined,
  ReloadOutlined,
} from "@ant-design/icons";

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
  identifying: "识别中",
  identified: "已识别",
  identify_failed: "识别失败",
  pricing: "回填报价",
  priced: "报价完成",
  price_partial: "报价部分成功",
  price_failed: "报价失败",
};

const STATUS_COLOR: Record<string, string> = {
  pending: "default",
  extracting: "processing",
  extracted: "blue",
  skipped: "default",
  partial: "warning",
  failed: "error",
  needs_password: "warning",
  identifying: "processing",
  identified: "cyan",
  identify_failed: "error",
  pricing: "processing",
  priced: "success",
  price_partial: "warning",
  price_failed: "error",
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
      // ignore
    } finally {
      setRetrying((p) => ({ ...p, [docId]: false }));
    }
  };

  if (documents.length === 0) {
    return (
      <Typography.Text
        type="secondary"
        style={{ fontSize: 13, padding: "8px 0", display: "block" }}
        data-testid="filetree-empty"
      >
        暂无文件
      </Typography.Text>
    );
  }

  const archives = documents.filter((d) =>
    ARCHIVE_TYPES.has(d.file_type.toLowerCase()),
  );
  const others = documents.filter(
    (d) => !ARCHIVE_TYPES.has(d.file_type.toLowerCase()),
  );

  const childrenByArchive: Record<string, BidDocument[]> = {};
  for (const f of others) {
    (childrenByArchive[f.source_archive] ??= []).push(f);
  }

  return (
    <div data-testid="filetree" style={{ fontSize: 13 }}>
      {archives.map((arc) => (
        <div key={arc.id} style={{ marginBottom: 10 }}>
          <Space size={8} wrap>
            <FolderOpenOutlined style={{ color: "#1d4584" }} />
            <Typography.Text strong style={{ fontSize: 13 }}>
              {arc.file_name}
            </Typography.Text>
            <StatusTag status={arc.parse_status} />
            {arc.parse_error && (
              <Button
                size="small"
                type="link"
                onClick={() =>
                  setOpenErrors((p) => ({ ...p, [arc.id]: !p[arc.id] }))
                }
                data-testid={`filetree-error-toggle-${arc.id}`}
                style={{ padding: "0 4px", fontSize: 11 }}
              >
                {openErrors[arc.id] ? "收起" : "查看错误"}
              </Button>
            )}
          </Space>
          {arc.parse_error && openErrors[arc.id] && (
            <div
              data-testid={`filetree-error-${arc.id}`}
              style={{
                marginLeft: 24,
                marginTop: 6,
                padding: "6px 10px",
                background: "#fdecec",
                border: "1px solid #f5c0c0",
                borderRadius: 4,
                color: "#c53030",
                fontSize: 12,
              }}
            >
              {arc.parse_error}
            </div>
          )}
          <ul
            style={{
              margin: "6px 0 0 24px",
              padding: 0,
              listStyle: "none",
            }}
          >
            {(childrenByArchive[arc.file_name] ?? []).map((child) => {
              const canEditRole =
                child.file_type === ".docx" || child.file_type === ".xlsx";
              const showRetry = FAILURE_STATUSES.has(child.parse_status);
              return (
                <li key={child.id} style={{ marginBottom: 4 }}>
                  <Space size={8} wrap>
                    <FileOutlined style={{ color: "#8a919d" }} />
                    <Typography.Text style={{ fontSize: 13 }}>
                      {child.file_name}
                    </Typography.Text>
                    <StatusTag status={child.parse_status} />
                    {canEditRole && (
                      <RoleDropdown
                        documentId={child.id}
                        role={child.file_role as DocumentRole | null}
                        confidence={child.role_confidence}
                        onChanged={() => onDocumentChanged?.()}
                      />
                    )}
                    {showRetry && (
                      <Button
                        size="small"
                        type="link"
                        icon={<ReloadOutlined />}
                        onClick={() => void handleRetry(child.id)}
                        loading={!!retrying[child.id]}
                        data-testid={`filetree-retry-${child.id}`}
                        style={{ fontSize: 11 }}
                      >
                        重试
                      </Button>
                    )}
                    {child.parse_error && (
                      <Typography.Text
                        type="secondary"
                        style={{ fontSize: 11 }}
                      >
                        {child.parse_error}
                      </Typography.Text>
                    )}
                  </Space>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </div>
  );
}

function StatusTag({ status }: { status: string }) {
  return (
    <Tag
      color={STATUS_COLOR[status] ?? "default"}
      data-testid={`status-badge-${status}`}
      style={{ margin: 0, fontSize: 11 }}
    >
      {STATUS_LABEL[status] ?? status}
    </Tag>
  );
}
