import { Breadcrumb, Card, Tag, Typography } from "antd";
import { Link } from "react-router-dom";
import { useSSE } from "../hooks/useSSE";

type Heartbeat = { seq: number; ts: string };

export default function SseDemoPage() {
  const { status, history } = useSSE<Heartbeat>("/demo/sse", {
    events: ["heartbeat"],
  });

  return (
    <div style={{ maxWidth: 960 }}>
      <Breadcrumb
        items={[
          { title: <Link to="/projects">项目</Link> },
          { title: "SSE 心跳演示" },
        ]}
        style={{ marginBottom: 12 }}
      />
      <Typography.Title level={3} style={{ margin: "0 0 4px", fontWeight: 600 }}>
        SSE 心跳演示
      </Typography.Title>
      <Typography.Paragraph type="secondary" style={{ margin: "0 0 20px" }}>
        内部调试用页,观察后端 /demo/sse 的心跳事件流
      </Typography.Paragraph>

      <Card variant="outlined" style={{ marginBottom: 12 }}>
        <Typography.Text style={{ fontSize: 13 }}>
          状态{" "}
          <Tag
            color={status === "open" ? "success" : status === "connecting" ? "processing" : "default"}
            data-testid="sse-status"
            style={{ margin: "0 6px" }}
          >
            {status}
          </Tag>
          · 收到{" "}
          <Typography.Text strong data-testid="sse-count">
            {history.length}
          </Typography.Text>{" "}
          条
        </Typography.Text>
      </Card>

      <Card variant="outlined" styles={{ body: { padding: 0 } }}>
        <ul
          data-testid="sse-list"
          style={{
            listStyle: "none",
            padding: 0,
            margin: 0,
            fontFamily: '"SF Mono", Menlo, Consolas, monospace',
            fontSize: 12,
          }}
        >
          {history
            .slice()
            .reverse()
            .map((h, i, arr) => (
              <li
                key={h.seq}
                style={{
                  padding: "10px 16px",
                  borderBottom: i < arr.length - 1 ? "1px solid #f0f2f5" : "none",
                  color: "#1f2328",
                }}
              >
                <span style={{ color: "#8a919d" }}>#{h.seq}</span>{" "}
                <span style={{ color: "#5c6370" }}>@ {h.receivedAt}</span>
                {" — "}
                <span>event={h.event}</span>
                {", "}
                <span>data={JSON.stringify(h.data)}</span>
              </li>
            ))}
        </ul>
      </Card>
    </div>
  );
}
