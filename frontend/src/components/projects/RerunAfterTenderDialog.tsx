/**
 * 上传招标文件后提示重跑检测 dialog(detect-tender-baseline §7.6)。
 *
 * 当项目已有 completed 检测版本,新上传招标文件后弹窗询问是否立即重跑;
 * 立即重跑 → 调启动检测;稍后 → 关闭,保留新 baseline 待下次手动启动。
 */
import { Alert, Button, Modal, Space, Typography } from "antd";

interface Props {
  open: boolean;
  onCancel: () => void;
  onConfirm: () => void;
  loading?: boolean;
}

export default function RerunAfterTenderDialog({
  open,
  onCancel,
  onConfirm,
  loading,
}: Props) {
  return (
    <Modal
      open={open}
      title="新基线已就绪"
      onCancel={onCancel}
      footer={null}
      destroyOnHidden
      width={480}
      wrapProps={{ "data-testid": "rerun-after-tender-dialog" }}
    >
      <Space direction="vertical" size={12} style={{ width: "100%" }}>
        <Alert
          type="info"
          showIcon
          message="招标文件已上传并解析"
          description="是否立即基于新基线重新检测?旧报告将保留,新版本与之并列展示。"
        />
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          也可稍后从项目详情页手动启动检测。
        </Typography.Text>
        <div
          style={{
            display: "flex",
            justifyContent: "flex-end",
            gap: 8,
            marginTop: 4,
          }}
        >
          <Button
            onClick={onCancel}
            disabled={loading}
            data-testid="rerun-cancel"
          >
            稍后
          </Button>
          <Button
            type="primary"
            onClick={onConfirm}
            loading={loading}
            data-testid="rerun-confirm"
          >
            立即重新检测
          </Button>
        </div>
      </Space>
    </Modal>
  );
}
