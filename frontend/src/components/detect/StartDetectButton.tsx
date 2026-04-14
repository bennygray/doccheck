/**
 * C6 StartDetectButton — 启动检测按钮
 *
 * - 前置条件 hover tooltip:bidder<2 / 有非终态 bidder / analyzing 中
 * - 点击调 POST /analysis/start;成功刷新;409 跳转进度面板
 */
import { useState } from "react";

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
          // 幂等:已在检测中 — 视为成功,交给 UI 跳到进度面板
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

  return (
    <div className="inline-flex flex-col">
      <button
        type="button"
        onClick={onClick}
        disabled={disabled}
        title={disabledReason ?? undefined}
        className={
          disabled
            ? "px-4 py-2 rounded bg-gray-300 text-gray-500 cursor-not-allowed"
            : "px-4 py-2 rounded bg-blue-600 text-white hover:bg-blue-700"
        }
      >
        {label}
      </button>
      {error && (
        <div className="mt-1 text-sm text-red-600" role="alert">
          {error}
        </div>
      )}
    </div>
  );
}
