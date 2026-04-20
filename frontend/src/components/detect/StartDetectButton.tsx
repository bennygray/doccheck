/**
 * C6 StartDetectButton — 启动检测按钮(antd 化)
 *
 * - 前置条件 tooltip:bidder<2 / 有非终态 bidder / analyzing 中
 * - 点击调 POST /analysis/start;409 幂等
 */
import { useState } from "react";
import { Alert, Button, Tooltip } from "antd";
import { PlayCircleOutlined } from "@ant-design/icons";

import { ApiError, api } from "../../services/api";
import type { BidderSummary } from "../../types";

const BIDDER_TERMINAL_STATES = new Set<string>([
  "identified",
  "priced",
  "price_partial",
  "identify_failed",
  "price_failed",
  "skipped",
  "needs_password",
  "failed",
  "extracted",
  "partial",
]);

export interface StartDetectButtonProps {
  projectId: number | string;
  projectStatus: string;
  bidders: BidderSummary[];
  onStarted?: (version: number) => void;
}

export function StartDetectButton({
  projectId,
  projectStatus,
  bidders,
  onStarted,
}: StartDetectButtonProps) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const bidderCount = bidders.length;
  const nonTerminal = bidders.filter(
    (b) => !BIDDER_TERMINAL_STATES.has(b.parse_status),
  );
  const isAnalyzing = projectStatus === "analyzing";

  let disabledReason: string | null = null;
  if (bidderCount < 2) {
    disabledReason = "至少需要2个投标人";
  } else if (nonTerminal.length > 0) {
    disabledReason = "请等待所有文件解析完成";
  } else if (isAnalyzing) {
    disabledReason = "检测正在进行中";
  }

  const disabled = disabledReason !== null || loading;
  const label = isAnalyzing
    ? "检测进行中"
    : loading
      ? "启动中..."
      : "启动检测";

  const onClick = async () => {
    setError(null);
    setLoading(true);
    try {
      const resp = await api.startAnalysis(projectId);
      onStarted?.(resp.version);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 409) {
          setError("已在检测中,请查看进度");
          onStarted?.(-1);
        } else {
          const msg =
            typeof err.detail === "string"
              ? err.detail
              : JSON.stringify(err.detail);
          setError(msg || "启动失败");
        }
      } else {
        setError("启动失败");
      }
    } finally {
      setLoading(false);
    }
  };

  const btn = (
    <Button
      type="primary"
      size="large"
      icon={<PlayCircleOutlined />}
      onClick={onClick}
      disabled={disabled}
      loading={loading}
      // 显式挂 title 方便屏幕阅读器 + 测试断言(antd Tooltip 走 hover,原生 title 兼容更稳)
      title={disabledReason ?? undefined}
    >
      {label}
    </Button>
  );

  return (
    <div style={{ display: "inline-flex", flexDirection: "column", gap: 8 }}>
      {disabledReason ? <Tooltip title={disabledReason}>{btn}</Tooltip> : btn}
      {error && (
        <Alert
          type="error"
          message={error}
          role="alert"
          showIcon
          style={{ marginTop: 4 }}
        />
      )}
    </div>
  );
}
