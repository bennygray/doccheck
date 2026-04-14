import { Link } from "react-router-dom";
import { useSSE } from "../hooks/useSSE";

type Heartbeat = { seq: number; ts: string };

export default function SseDemoPage() {
  const { status, history } = useSSE<Heartbeat>("/demo/sse", {
    events: ["heartbeat"],
  });

  return (
    <main style={{ padding: 32, fontFamily: "system-ui, sans-serif" }}>
      <h1>SSE 心跳演示</h1>
      <p>
        状态: <code data-testid="sse-status">{status}</code> · 收到{" "}
        <code data-testid="sse-count">{history.length}</code> 条
      </p>
      <nav style={{ marginTop: 16 }}>
        <Link to="/">← 返回首页</Link>
      </nav>
      <ul style={{ marginTop: 24, fontFamily: "monospace" }} data-testid="sse-list">
        {history
          .slice()
          .reverse()
          .map((h) => (
            <li key={h.seq}>
              #{h.seq} @ {h.receivedAt} — event={h.event}, data=
              {JSON.stringify(h.data)}
            </li>
          ))}
      </ul>
    </main>
  );
}
