import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../services/api";

export default function HomePage() {
  const [health, setHealth] = useState<string>("checking...");

  useEffect(() => {
    api
      .health()
      .then((r) => setHealth(JSON.stringify(r)))
      .catch((e) => setHealth(`error: ${e.message}`));
  }, []);

  return (
    <main style={{ padding: 32, fontFamily: "system-ui, sans-serif" }}>
      <h1>围标检测系统</h1>
      <p>DocumentCheck — C1 infra-base 骨架</p>
      <section style={{ marginTop: 16 }}>
        <strong>后端健康:</strong>
        <code data-testid="health-status" style={{ marginLeft: 8 }}>
          {health}
        </code>
      </section>
      <nav style={{ marginTop: 24 }}>
        <Link to="/demo/sse">→ SSE 心跳演示</Link>
      </nav>
    </main>
  );
}
