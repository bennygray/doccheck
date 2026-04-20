/**
 * 已有投标人追加上传按钮 (US-3.2, C4 file-upload §8.2)。
 *
 * 重用 AddBidderDialog 的文件校验逻辑;调 api.uploadToBidder。
 */
import { useRef, useState } from "react";
import { Button, Typography } from "antd";
import { UploadOutlined } from "@ant-design/icons";
import { ApiError, api } from "../../services/api";
import type { UploadResult } from "../../types";

const ALLOWED_EXTS = [".zip", ".7z", ".rar"] as const;
const MAX_FILE_BYTES = 500 * 1024 * 1024;

interface Props {
  projectId: number;
  bidderId: number;
  onUploaded: (result: UploadResult) => void;
}

function getExt(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot >= 0 ? name.slice(dot).toLowerCase() : "";
}

export default function UploadButton({ projectId, bidderId, onUploaded }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function pick(f: File | null) {
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
    setSubmitting(true);
    try {
      const result = await api.uploadToBidder(projectId, bidderId, f);
      onUploaded(result);
    } catch (err) {
      if (err instanceof ApiError && err.status === 415) {
        setError("文件类型校验失败");
      } else if (err instanceof ApiError && err.status === 413) {
        setError("文件超过 500MB 限制");
      } else if (err instanceof ApiError) {
        setError(`上传失败 (${err.status})`);
      } else {
        setError("上传失败,请稍后重试");
      }
    } finally {
      setSubmitting(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  return (
    <span style={{ display: "inline-flex", gap: 8, alignItems: "center" }}>
      <Button
        size="small"
        icon={<UploadOutlined />}
        data-testid={`upload-btn-${bidderId}`}
        onClick={() => inputRef.current?.click()}
        loading={submitting}
      >
        {submitting ? "上传中" : "追加上传"}
      </Button>
      <input
        ref={inputRef}
        type="file"
        accept=".zip,.7z,.rar"
        data-testid={`upload-file-${bidderId}`}
        onChange={(e) => void pick(e.target.files?.[0] ?? null)}
        style={{ display: "none" }}
      />
      {error && (
        <Typography.Text type="danger" style={{ fontSize: 12 }}>
          {error}
        </Typography.Text>
      )}
    </span>
  );
}
