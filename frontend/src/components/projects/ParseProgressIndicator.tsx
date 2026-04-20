/**
 * C5 项目顶栏解析进度指示器
 *
 * antd 化:横向 Progress 进度条 + 平铺计数标签(避免 Badge 悬浮徽章的视觉混乱)
 * 保留所有 data-testid
 */
import { Progress, Typography } from "antd";
import type { ProjectProgress } from "../../types";

interface Props {
  progress: ProjectProgress | null;
  connected: boolean;
}

function Stat({
  label,
  value,
  valueColor,
  testid,
}: {
  label: string;
  value: number;
  valueColor?: string;
  testid?: string;
}) {
  return (
    <span
      data-testid={testid}
      style={{
        display: "inline-flex",
        alignItems: "baseline",
        gap: 4,
        fontSize: 13,
      }}
    >
      <span style={{ color: "#8a919d" }}>{label}</span>
      <span
        style={{
          color: valueColor ?? "#1f2328",
          fontWeight: 600,
        }}
      >
        {value}
      </span>
    </span>
  );
}

export default function ParseProgressIndicator({ progress, connected }: Props) {
  if (!progress) return null;

  const total = progress.total_bidders || 0;
  const identified =
    progress.identified_count +
    progress.priced_count +
    progress.pricing_count;
  const priced = progress.priced_count;
  const failed = progress.failed_count;
  const partial = progress.partial_count;

  const pricedPct = total > 0 ? Math.round((priced / total) * 100) : 0;

  return (
    <div data-testid="parse-progress-indicator">
      {total > 0 && (
        <Progress
          percent={pricedPct}
          strokeColor="#1d4584"
          trailColor="#f0f2f5"
          size="small"
          format={(p) => (
            <span style={{ fontSize: 12, color: "#5c6370" }}>{p}%</span>
          )}
          style={{ marginBottom: 10 }}
        />
      )}

      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 20,
          flexWrap: "wrap",
        }}
      >
        <span
          data-testid="progress-total"
          style={{
            display: "inline-flex",
            alignItems: "baseline",
            gap: 4,
            fontSize: 13,
          }}
        >
          <Typography.Text type="secondary">共 </Typography.Text>
          <Typography.Text strong>{total}</Typography.Text>
          <Typography.Text type="secondary"> 个投标人</Typography.Text>
        </span>

        <Stat
          label="已识别"
          value={identified}
          valueColor={identified > 0 ? "#1d4584" : undefined}
          testid="progress-identified"
        />
        <Stat
          label="已回填报价"
          value={priced}
          valueColor={priced > 0 ? "#2d7a4a" : undefined}
          testid="progress-priced"
        />
        {partial > 0 && (
          <Stat
            label="部分失败"
            value={partial}
            valueColor="#c27c0e"
            testid="progress-partial"
          />
        )}
        {failed > 0 && (
          <Stat
            label="失败"
            value={failed}
            valueColor="#c53030"
            testid="progress-failed"
          />
        )}

        <span
          data-testid="progress-connection"
          style={{
            marginLeft: "auto",
            fontSize: 12,
            display: "inline-flex",
            alignItems: "center",
            gap: 5,
          }}
        >
          <span
            style={{
              width: 6,
              height: 6,
              borderRadius: "50%",
              background: connected ? "#2d7a4a" : "#b1b6bf",
              display: "inline-block",
            }}
          />
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {connected ? "实时" : "轮询兜底"}
          </Typography.Text>
        </span>
      </div>
    </div>
  );
}
