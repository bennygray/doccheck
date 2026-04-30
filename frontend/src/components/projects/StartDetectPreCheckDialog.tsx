/**
 * 启动检测前预检查 dialog(detect-tender-baseline §7.5)。
 *
 * 当项目未上传招标文件时,启动检测前弹窗提示基线降级风险;
 * 用户勾选"不再提醒"后写入 localStorage,下次同项目跳过该弹窗。
 */
import { useState } from "react";
import { Alert, Button, Checkbox, Modal, Space, Typography } from "antd";

const STORAGE_KEY_PREFIX = "tender_baseline_warning_dismissed_";

export function dismissedStorageKey(projectId: number | string): string {
  return `${STORAGE_KEY_PREFIX}${projectId}`;
}

export function shouldSkipPreCheckDialog(projectId: number | string): boolean {
  try {
    return window.localStorage.getItem(dismissedStorageKey(projectId)) === "1";
  } catch {
    return false;
  }
}

interface Props {
  projectId: number | string;
  open: boolean;
  hasTender: boolean;
  bidderCount: number;
  onCancel: () => void;
  onConfirm: () => void;
}

export default function StartDetectPreCheckDialog({
  projectId,
  open,
  hasTender,
  bidderCount,
  onCancel,
  onConfirm,
}: Props) {
  const [dontRemind, setDontRemind] = useState(false);

  function handleConfirm() {
    if (dontRemind) {
      try {
        window.localStorage.setItem(dismissedStorageKey(projectId), "1");
      } catch {
        // 忽略隐私模式 / 配额超限
      }
    }
    onConfirm();
  }

  const lowBidderCount = bidderCount > 0 && bidderCount < 3;

  return (
    <Modal
      open={open}
      title="启动检测前确认"
      onCancel={onCancel}
      footer={null}
      destroyOnHidden
      width={520}
      wrapProps={{ "data-testid": "start-detect-precheck-dialog" }}
    >
      <Space direction="vertical" size={12} style={{ width: "100%" }}>
        {!hasTender && (
          <Alert
            type="warning"
            showIcon
            message="未上传招标文件"
            description={
              lowBidderCount
                ? `仅 ${bidderCount} 家投标方,共识基线不可用,基线判定将降级到 L3(无基线),误报率可能升高。`
                : "将自动启用 L2 共识基线(≥3 投标方时跨方共识识别模板段),精度略低于 L1。建议补充上传招标文件后重跑,可获得更精确的判定。"
            }
            data-testid="precheck-no-tender-alert"
          />
        )}
        {hasTender && (
          <Alert
            type="info"
            showIcon
            message="将以 L1 招标基线启动检测"
            description="已上传招标文件,模板段命中招标 hash 时自动剔除铁证。"
          />
        )}

        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          检测启动后将以异步任务运行,可在项目详情页查看进度。
        </Typography.Text>

        <Checkbox
          data-testid="precheck-dont-remind"
          checked={dontRemind}
          onChange={(e) => setDontRemind(e.target.checked)}
        >
          本项目不再提醒
        </Checkbox>

        <div
          style={{
            display: "flex",
            justifyContent: "flex-end",
            gap: 8,
            marginTop: 4,
          }}
        >
          <Button onClick={onCancel} data-testid="precheck-cancel">
            取消
          </Button>
          <Button
            type="primary"
            onClick={handleConfirm}
            data-testid="precheck-confirm"
          >
            确认启动
          </Button>
        </div>
      </Space>
    </Modal>
  );
}
