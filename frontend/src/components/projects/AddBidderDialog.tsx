/**
 * 添加投标人弹窗 (US-3.1, C4 file-upload §8.1)。
 *
 * antd 化:Modal + Form + 拖拽上传区(保留 drag/drop 原生逻辑);
 * data-testid 保留:add-bidder-dialog / bidder-name-input / bidder-file-zone /
 *   bidder-file-input / bidder-file-name / bidder-form-error / bidder-submit
 */
import { useRef, useState } from "react";
import { Alert, Button, Form, Input, Modal, Typography } from "antd";
import { InboxOutlined } from "@ant-design/icons";
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

  async function handleSubmit(e: React.SyntheticEvent) {
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
    <Modal
      open
      title="添加投标人"
      onCancel={onClose}
      footer={null}
      destroyOnHidden
      width={520}
      // 外层 div 挂 data-testid,与旧版契约保持一致
      wrapProps={{
        "data-testid": "add-bidder-dialog",
      }}
    >
      <Form
        layout="vertical"
        component="form"
        onSubmitCapture={handleSubmit}
        requiredMark={false}
      >
        <Form.Item label="投标人名称" required>
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            data-testid="bidder-name-input"
            maxLength={200}
            autoFocus
            placeholder="如:XX 建筑工程有限公司"
          />
        </Form.Item>

        <Form.Item
          label="压缩包(可选)"
          extra="支持 .zip / .7z / .rar,最大 500MB"
        >
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
            onClick={() => inputRef.current?.click()}
            style={{
              border: "2px dashed",
              borderColor: dragActive ? "#1d4584" : "#d5dae2",
              borderRadius: 8,
              padding: 20,
              textAlign: "center",
              cursor: "pointer",
              background: dragActive ? "#eef3fb" : "#fafbfc",
              transition: "all 0.15s ease",
            }}
          >
            <InboxOutlined
              style={{
                fontSize: 32,
                color: dragActive ? "#1d4584" : "#8a919d",
                marginBottom: 8,
              }}
            />
            {file ? (
              <div>
                <Typography.Text strong data-testid="bidder-file-name">
                  {file.name}
                </Typography.Text>
                <div style={{ fontSize: 12, color: "#8a919d", marginTop: 2 }}>
                  {Math.round(file.size / 1024)} KB
                </div>
              </div>
            ) : (
              <div>
                <Typography.Text style={{ fontSize: 13 }}>
                  点击或拖拽文件到此处
                </Typography.Text>
                <div style={{ fontSize: 12, color: "#8a919d", marginTop: 2 }}>
                  .zip / .7z / .rar,最大 500MB
                </div>
              </div>
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
        </Form.Item>

        {error && (
          <Alert
            type="error"
            message={error}
            showIcon
            data-testid="bidder-form-error"
            style={{ marginBottom: 12 }}
          />
        )}

        <div
          style={{
            display: "flex",
            gap: 8,
            justifyContent: "flex-end",
            marginTop: 8,
          }}
        >
          <Button onClick={onClose} disabled={submitting}>
            取消
          </Button>
          <Button
            type="primary"
            htmlType="submit"
            loading={submitting}
            data-testid="bidder-submit"
          >
            {submitting ? "创建中" : "创建"}
          </Button>
        </div>
      </Form>
    </Modal>
  );
}
