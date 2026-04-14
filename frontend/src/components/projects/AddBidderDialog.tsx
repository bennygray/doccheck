/**
 * 添加投标人弹窗 (US-3.1, C4 file-upload §8.1)。
 *
 * - name 输入(必填、≤200)
 * - file 选填:原生 file input + drag-drop 双入口(D10)
 * - 前端校验:扩展名 + 大小 ≤500MB
 * - 提交后调 `api.createBidder(projectId, name, file?)`,失败弹错码
 */
import { useEffect, useRef, useState } from "react";
import { ApiError, api } from "../../services/api";
import type { Bidder } from "../../types";

const ALLOWED_EXTS = [".zip", ".7z", ".rar"] as const;
const MAX_FILE_BYTES = 500 * 1024 * 1024;

interface Props {
  projectId: number;
  onClose: () => void;
  onCreated: (bidder: Bidder) => void;
}

function getExt(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot >= 0 ? name.slice(dot).toLowerCase() : "";
}

export default function AddBidderDialog({ projectId, onClose, onCreated }: Props) {
  const [name, setName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  // ESC 关闭(键盘可达)
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  function pickFile(f: File | null) {
    setError(null);
    if (!f) {
      setFile(null);
      return;
    }
    const ext = getExt(f.name);
    if (!ALLOWED_EXTS.includes(ext as (typeof ALLOWED_EXTS)[number])) {
      setError(`仅支持 ${ALLOWED_EXTS.join(" / ")} 格式`);
      return;
    }
    if (f.size > MAX_FILE_BYTES) {
      setError("文件超过 500MB 限制");
      return;
    }
    setFile(f);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const trimmed = name.trim();
    if (!trimmed) {
      setError("投标人名称不能为空");
      return;
    }
    if (trimmed.length > 200) {
      setError("名称不能超过 200 字符");
      return;
    }
    setSubmitting(true);
    try {
      const bidder = await api.createBidder(projectId, trimmed, file);
      onCreated(bidder);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError("同项目内已有该投标人");
      } else if (err instanceof ApiError && err.status === 415) {
        setError("文件类型校验失败(魔数与扩展名不匹配)");
      } else if (err instanceof ApiError && err.status === 413) {
        setError("文件超过 500MB 限制");
      } else if (err instanceof ApiError) {
        setError(`创建失败 (${err.status})`);
      } else {
        setError("创建失败,请稍后重试");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      data-testid="add-bidder-dialog"
      role="dialog"
      aria-modal="true"
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.4)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 100,
      }}
      onClick={onClose}
    >
      <form
        onSubmit={handleSubmit}
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "#fff",
          padding: 24,
          borderRadius: 8,
          minWidth: 420,
          maxWidth: "90vw",
        }}
      >
        <h2 style={{ marginTop: 0, fontSize: 18 }}>添加投标人</h2>

        <label style={{ display: "block", marginTop: 12 }}>
          投标人名称 *
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            data-testid="bidder-name-input"
            maxLength={200}
            autoFocus
            style={{
              display: "block",
              width: "100%",
              padding: 8,
              marginTop: 4,
              boxSizing: "border-box",
            }}
          />
        </label>

        <div
          data-testid="bidder-file-zone"
          onDragOver={(e) => {
            e.preventDefault();
            setDragActive(true);
          }}
          onDragLeave={() => setDragActive(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragActive(false);
            pickFile(e.dataTransfer.files?.[0] ?? null);
          }}
          style={{
            border: "2px dashed",
            borderColor: dragActive ? "#1677ff" : "#ccc",
            borderRadius: 4,
            padding: 16,
            marginTop: 12,
            textAlign: "center",
            cursor: "pointer",
          }}
          onClick={() => inputRef.current?.click()}
        >
          {file ? (
            <span data-testid="bidder-file-name">
              {file.name} ({Math.round(file.size / 1024)} KB)
            </span>
          ) : (
            <span style={{ color: "#888" }}>
              拖拽或点击选择压缩包(.zip / .7z / .rar,可选)
            </span>
          )}
          <input
            ref={inputRef}
            type="file"
            data-testid="bidder-file-input"
            accept=".zip,.7z,.rar"
            onChange={(e) => pickFile(e.target.files?.[0] ?? null)}
            style={{ display: "none" }}
          />
        </div>

        {error && (
          <p
            data-testid="bidder-form-error"
            style={{ color: "#c00", marginTop: 12 }}
          >
            {error}
          </p>
        )}

        <div
          style={{
            marginTop: 16,
            display: "flex",
            gap: 8,
            justifyContent: "flex-end",
          }}
        >
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            style={{ padding: "6px 16px" }}
          >
            取消
          </button>
          <button
            type="submit"
            data-testid="bidder-submit"
            disabled={submitting}
            style={{
              padding: "6px 16px",
              background: "#1677ff",
              color: "#fff",
              border: 0,
            }}
          >
            {submitting ? "创建中..." : "创建"}
          </button>
        </div>
      </form>
    </div>
  );
}
