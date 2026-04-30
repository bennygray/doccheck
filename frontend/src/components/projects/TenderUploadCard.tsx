/**
 * 招标文件上传卡(detect-tender-baseline §7.3)。
 *
 * 拖拽上传单份招标文件(.docx / .xlsx / .zip / .7z / .rar,500MB 上限),
 * 上传后展示已存在的招标文件列表 + 解析状态,支持软删除。
 *
 * 注:本次 change 不抽 useDragDrop hook(避免范围爆炸),
 * drag-drop 内联代码与 AddBidderDialog 保持等价(后续 follow-up change 再抽公共 hook)。
 */
import { useEffect, useRef, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Empty,
  Space,
  Tag,
  Typography,
} from "antd";
import {
  DeleteOutlined,
  InboxOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import { ApiError, api } from "../../services/api";
import type { TenderDocument } from "../../types";

const ALLOWED_EXTS = [".docx", ".xlsx", ".zip", ".7z", ".rar"] as const;
const MAX_FILE_BYTES = 500 * 1024 * 1024;

const STATUS_LABEL: Record<string, string> = {
  pending: "待解析",
  parsing: "解析中",
  extracted: "已解析",
  failed: "解析失败",
};
const STATUS_COLOR: Record<string, string> = {
  pending: "default",
  parsing: "processing",
  extracted: "success",
  failed: "error",
};

interface Props {
  projectId: number;
  onChanged?: () => void;
}

function getExt(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot >= 0 ? name.slice(dot).toLowerCase() : "";
}

export default function TenderUploadCard({ projectId, onChanged }: Props) {
  const [tenders, setTenders] = useState<TenderDocument[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  async function reload() {
    setLoading(true);
    try {
      const list = await api.listTenders(projectId);
      setTenders(list);
      setError(null);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(`加载失败 (${err.status})`);
      } else {
        setError("加载失败,请稍后重试");
      }
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  async function uploadFile(f: File | null) {
    setError(null);
    if (!f) return;
    const ext = getExt(f.name);
    if (!ALLOWED_EXTS.includes(ext as (typeof ALLOWED_EXTS)[number])) {
      setError(`仅支持 ${ALLOWED_EXTS.join(" / ")} 格式`);
      return;
    }
    if (f.size > MAX_FILE_BYTES) {
      setError("文件超过 500MB 限制");
      return;
    }
    setUploading(true);
    try {
      await api.uploadTender(projectId, f);
      await reload();
      onChanged?.();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError("该招标文件已上传(MD5 重复)");
      } else if (err instanceof ApiError && err.status === 415) {
        setError("文件类型校验失败(魔数与扩展名不匹配)");
      } else if (err instanceof ApiError && err.status === 413) {
        setError("文件超过 500MB 限制");
      } else if (err instanceof ApiError) {
        setError(`上传失败 (${err.status})`);
      } else {
        setError("上传失败,请稍后重试");
      }
    } finally {
      setUploading(false);
    }
  }

  async function onDelete(tender: TenderDocument) {
    setError(null);
    try {
      await api.deleteTender(projectId, tender.id);
      await reload();
      onChanged?.();
    } catch (err) {
      if (err instanceof ApiError) {
        setError(`删除失败 (${err.status})`);
      } else {
        setError("删除失败");
      }
    }
  }

  return (
    <Card
      variant="outlined"
      data-testid="tender-section"
      styles={{ body: { padding: 0 } }}
    >
      <div
        style={{
          padding: "16px 20px",
          borderBottom: "1px solid #f0f2f5",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <Space size={8} align="center">
          <Typography.Title level={5} style={{ margin: 0, fontWeight: 600 }}>
            招标文件
          </Typography.Title>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            共 {tenders.length} 份 · 用于建立模板基线(L1)
          </Typography.Text>
        </Space>
        <Button
          size="small"
          type="text"
          icon={<ReloadOutlined />}
          onClick={() => void reload()}
          loading={loading}
          aria-label="刷新"
          data-testid="tender-refresh"
        />
      </div>

      <div style={{ padding: 20 }}>
        <div
          data-testid="tender-file-zone"
          onDragOver={(e) => {
            e.preventDefault();
            setDragActive(true);
          }}
          onDragLeave={() => setDragActive(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragActive(false);
            void uploadFile(e.dataTransfer.files?.[0] ?? null);
          }}
          onClick={() => inputRef.current?.click()}
          style={{
            border: "2px dashed",
            borderColor: dragActive ? "#1d4584" : "#d5dae2",
            borderRadius: 8,
            padding: 20,
            textAlign: "center",
            cursor: uploading ? "wait" : "pointer",
            background: dragActive ? "#eef3fb" : "#fafbfc",
            transition: "all 0.15s ease",
            opacity: uploading ? 0.6 : 1,
          }}
        >
          <InboxOutlined
            style={{
              fontSize: 32,
              color: dragActive ? "#1d4584" : "#8a919d",
              marginBottom: 8,
            }}
          />
          <div>
            <Typography.Text style={{ fontSize: 13 }}>
              {uploading ? "上传中..." : "点击或拖拽文件到此处上传招标文件"}
            </Typography.Text>
            <div style={{ fontSize: 12, color: "#8a919d", marginTop: 2 }}>
              .docx / .xlsx / .zip / .7z / .rar,最大 500MB
            </div>
          </div>
          <input
            ref={inputRef}
            type="file"
            data-testid="tender-file-input"
            accept=".docx,.xlsx,.zip,.7z,.rar"
            onChange={(e) => {
              const f = e.target.files?.[0] ?? null;
              e.target.value = "";
              void uploadFile(f);
            }}
            style={{ display: "none" }}
            disabled={uploading}
          />
        </div>

        {error && (
          <Alert
            type="error"
            message={error}
            showIcon
            data-testid="tender-error"
            style={{ marginTop: 12 }}
          />
        )}

        <div style={{ marginTop: 16 }}>
          {tenders.length === 0 ? (
            <Empty
              description={
                <span data-testid="tender-empty" style={{ color: "#8a919d", fontSize: 13 }}>
                  暂无招标文件,上传后基线判定降级至 L2/L3
                </span>
              }
              image={Empty.PRESENTED_IMAGE_SIMPLE}
            />
          ) : (
            <div>
              {tenders.map((t, idx) => (
                <div
                  key={t.id}
                  data-testid={`tender-row-${t.id}`}
                  style={{
                    padding: "12px 4px",
                    borderTop: idx === 0 ? "none" : "1px solid #f0f2f5",
                    display: "flex",
                    alignItems: "center",
                    gap: 12,
                  }}
                >
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <Typography.Text
                      strong
                      style={{
                        fontSize: 13,
                        display: "block",
                        whiteSpace: "nowrap",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                      }}
                    >
                      {t.file_name}
                    </Typography.Text>
                    <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                      {Math.round(t.file_size / 1024)} KB ·{" "}
                      {new Date(t.created_at).toLocaleString()}
                    </Typography.Text>
                  </div>
                  <Tag
                    color={STATUS_COLOR[t.parse_status] ?? "default"}
                    data-testid={`tender-status-${t.id}`}
                    style={{ margin: 0 }}
                  >
                    {STATUS_LABEL[t.parse_status] ?? t.parse_status}
                  </Tag>
                  <Button
                    size="small"
                    type="text"
                    danger
                    icon={<DeleteOutlined />}
                    onClick={() => void onDelete(t)}
                    aria-label="删除招标文件"
                    data-testid={`tender-delete-${t.id}`}
                  />
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}
