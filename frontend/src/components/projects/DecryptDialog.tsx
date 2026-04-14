/**
 * 加密包密码重试弹窗 (D2, C4 file-upload §8.4)。
 *
 * 调 api.decryptDocument(documentId, password) → 后端 202 → 由父组件继续轮询
 * documents 列表观察 status 转换。
 */
import { useEffect, useState } from "react";
import { ApiError, api } from "../../services/api";

interface Props {
  documentId: number;
  fileName: string;
  onClose: () => void;
  onSubmitted: () => void;
}

export default function DecryptDialog({
  documentId,
  fileName,
  onClose,
  onSubmitted,
}: Props) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!password) {
      setError("密码不能为空");
      return;
    }
    setSubmitting(true);
    try {
      await api.decryptDocument(documentId, password);
      onSubmitted();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError("当前状态不需要密码");
      } else if (err instanceof ApiError) {
        setError(`提交失败 (${err.status})`);
      } else {
        setError("提交失败,请稍后重试");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      data-testid="decrypt-dialog"
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
        onSubmit={submit}
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "#fff",
          padding: 24,
          borderRadius: 8,
          minWidth: 360,
        }}
      >
        <h2 style={{ marginTop: 0, fontSize: 18 }}>解密压缩包</h2>
        <p style={{ color: "#666" }}>{fileName}</p>
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          data-testid="decrypt-password"
          autoFocus
          style={{
            display: "block",
            width: "100%",
            padding: 8,
            marginTop: 8,
            boxSizing: "border-box",
          }}
          placeholder="输入密码"
        />
        {error && (
          <p
            data-testid="decrypt-error"
            style={{ color: "#c00", marginTop: 8 }}
          >
            {error}
          </p>
        )}
        <div
          style={{ marginTop: 12, display: "flex", gap: 8, justifyContent: "flex-end" }}
        >
          <button type="button" onClick={onClose} disabled={submitting}>
            取消
          </button>
          <button
            type="submit"
            data-testid="decrypt-submit"
            disabled={submitting}
            style={{ background: "#1677ff", color: "#fff", border: 0, padding: "4px 16px" }}
          >
            {submitting ? "提交中..." : "提交"}
          </button>
        </div>
      </form>
    </div>
  );
}
