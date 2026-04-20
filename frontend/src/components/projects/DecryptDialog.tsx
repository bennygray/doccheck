/**
 * 加密包密码重试弹窗 (D2, C4 file-upload §8.4)。
 *
 * antd 化:Modal + Form + Input.Password
 */
import { useState } from "react";
import { Alert, Button, Form, Input, Modal, Typography } from "antd";
import { LockOutlined } from "@ant-design/icons";
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

  async function submit(e: React.SyntheticEvent) {
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
    <Modal
      open
      title="解密压缩包"
      onCancel={onClose}
      footer={null}
      destroyOnHidden
      width={440}
      wrapProps={{ "data-testid": "decrypt-dialog" }}
    >
      <Typography.Paragraph
        type="secondary"
        style={{ fontSize: 13, margin: "0 0 16px" }}
      >
        {fileName}
      </Typography.Paragraph>
      <Form
        layout="vertical"
        component="form"
        onSubmitCapture={submit}
        requiredMark={false}
      >
        <Form.Item label="密码" required>
          <Input.Password
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            data-testid="decrypt-password"
            autoFocus
            placeholder="输入解压密码"
            prefix={<LockOutlined style={{ color: "#8a919d" }} />}
          />
        </Form.Item>

        {error && (
          <Alert
            type="error"
            message={error}
            showIcon
            data-testid="decrypt-error"
            style={{ marginBottom: 12 }}
          />
        )}

        <div
          style={{
            display: "flex",
            gap: 8,
            justifyContent: "flex-end",
          }}
        >
          <Button onClick={onClose} disabled={submitting}>
            取消
          </Button>
          <Button
            type="primary"
            htmlType="submit"
            loading={submitting}
            data-testid="decrypt-submit"
          >
            {submitting ? "提交中" : "提交"}
          </Button>
        </div>
      </Form>
    </Modal>
  );
}
