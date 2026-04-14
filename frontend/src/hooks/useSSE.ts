import { useEffect, useRef, useState } from "react";

export type SSEEvent<T = unknown> = {
  seq: number;
  event: string;
  data: T;
  receivedAt: string;
};

export type SSEStatus = "connecting" | "open" | "closed";

export interface UseSSEOptions {
  /** 关注哪些 event 名(默认 ["heartbeat"]);`__any__` 表示全收 */
  events?: string[];
  /** 断连后自动重连(由浏览器原生 EventSource 保证) */
}

/** 订阅 SSE 端点的 React hook。基于原生 EventSource(浏览器内置自动重连)。 */
export function useSSE<T = unknown>(url: string, options: UseSSEOptions = {}) {
  const { events = ["heartbeat"] } = options;
  const [status, setStatus] = useState<SSEStatus>("connecting");
  const [latest, setLatest] = useState<SSEEvent<T> | null>(null);
  const [history, setHistory] = useState<SSEEvent<T>[]>([]);
  const seqRef = useRef(0);

  useEffect(() => {
    const es = new EventSource(url);
    setStatus("connecting");

    es.onopen = () => setStatus("open");
    es.onerror = () => setStatus("closed");

    const handler = (evt: MessageEvent, eventName: string) => {
      seqRef.current += 1;
      let parsed: T;
      try {
        parsed = JSON.parse(evt.data) as T;
      } catch {
        parsed = evt.data as unknown as T;
      }
      const item: SSEEvent<T> = {
        seq: seqRef.current,
        event: eventName,
        data: parsed,
        receivedAt: new Date().toISOString(),
      };
      setLatest(item);
      setHistory((prev) => [...prev.slice(-99), item]);
    };

    for (const name of events) {
      es.addEventListener(name, (evt) => handler(evt as MessageEvent, name));
    }

    return () => {
      es.close();
      setStatus("closed");
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, events.join(",")]);

  return { status, latest, history };
}
