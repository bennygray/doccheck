/**
 * C5 项目顶栏解析进度指示器
 *
 * 展示 ProjectProgress 的分阶段计数 + SSE 连接状态(连上 / 轮询兜底)。
 */
import type { ProjectProgress } from "../../types";

interface Props {
  progress: ProjectProgress | null;
  connected: boolean;
}

export default function ParseProgressIndicator({
  progress,
  connected,
}: Props) {
  if (!progress) return null;

  const total = progress.total_bidders || 0;
  const identified = progress.identified_count + progress.priced_count + progress.pricing_count;
  const priced = progress.priced_count;
  const failed = progress.failed_count;
  const partial = progress.partial_count;

  return (
    <div
      data-testid="parse-progress-indicator"
      style={{
        display: "flex",
        gap: 12,
        alignItems: "center",
        padding: "6px 10px",
        background: "#fafafa",
        border: "1px solid #e0e0e0",
        borderRadius: 4,
        fontSize: 13,
      }}
    >
      <span data-testid="progress-total">共 {total} 个投标人</span>
      <span
        data-testid="progress-identified"
        style={{ color: identified > 0 ? "#1976d2" : "#888" }}
      >
        已识别 {identified}
      </span>
      <span
        data-testid="progress-priced"
        style={{ color: priced > 0 ? "#388e3c" : "#888" }}
      >
        已回填报价 {priced}
      </span>
      {partial > 0 && (
        <span data-testid="progress-partial" style={{ color: "#f57c00" }}>
          部分失败 {partial}
        </span>
      )}
      {failed > 0 && (
        <span data-testid="progress-failed" style={{ color: "#d32f2f" }}>
          失败 {failed}
        </span>
      )}
      <span
        data-testid="progress-connection"
        style={{
          marginLeft: "auto",
          color: connected ? "#388e3c" : "#888",
          fontSize: 12,
        }}
      >
        {connected ? "● 实时" : "○ 轮询兜底"}
      </span>
    </div>
  );
}
