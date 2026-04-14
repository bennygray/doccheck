/**
 * C5 解析进度 hook (B1 + CLAUDE.md 兜底原则)
 *
 * - 主路径: EventSource 订阅 `/api/projects/{pid}/parse-progress`
 * - 断线兜底: onerror 后每 3s 轮询 `getProject(pid)`,重连成功后清 interval
 * - 自动根据事件更新 bidders / progress 本地状态
 */
import { useEffect, useRef, useState } from "react";

import { api } from "../services/api";
import { authStorage } from "../contexts/AuthContext";
import type {
  BidderSummary,
  ParseProgressEvent,
  ProjectDetail,
  ProjectProgress,
} from "../types";

export interface ParseProgressState {
  bidders: BidderSummary[];
  progress: ProjectProgress | null;
  /** SSE 已建立长连接,false = 走轮询兜底 */
  connected: boolean;
  /** 最近一条事件(调试/测试用) */
  lastEvent: ParseProgressEvent | null;
}

const POLL_INTERVAL_MS = 3000;

export function useParseProgress(
  projectId: number | string | null,
): ParseProgressState {
  const [bidders, setBidders] = useState<BidderSummary[]>([]);
  const [progress, setProgress] = useState<ProjectProgress | null>(null);
  const [connected, setConnected] = useState(false);
  const [lastEvent, setLastEvent] = useState<ParseProgressEvent | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (projectId == null) return;

    const refetch = async () => {
      try {
        const detail: ProjectDetail = await api.getProject(projectId);
        setBidders(detail.bidders);
        setProgress(detail.progress);
      } catch {
        // 网络错误静默,下次 poll 重试
      }
    };

    const startPolling = () => {
      if (pollRef.current) return;
      pollRef.current = setInterval(() => void refetch(), POLL_INTERVAL_MS);
    };

    const stopPolling = () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };

    // 初始拉一次做基线
    void refetch();

    // EventSource 不支持自定义 header → token 通过 query 附加
    const token = authStorage.getToken();
    const urlBase = api.parseProgressUrl(projectId);
    const url = token
      ? `${urlBase}?access_token=${encodeURIComponent(token)}`
      : urlBase;

    const es = new EventSource(url, { withCredentials: false });

    es.onopen = () => {
      setConnected(true);
      stopPolling();
    };

    es.onerror = () => {
      setConnected(false);
      startPolling();
    };

    const handler = (eventType: ParseProgressEvent["event_type"]) =>
      (evt: MessageEvent) => {
        let data: Record<string, unknown> = {};
        try {
          data = JSON.parse(evt.data);
        } catch {
          // data 不是 JSON,跳过
        }
        const event: ParseProgressEvent = { event_type: eventType, data };
        setLastEvent(event);

        if (eventType === "snapshot") {
          const snap = data as {
            bidders?: BidderSummary[];
            progress?: ProjectProgress;
          };
          if (snap.bidders) setBidders(snap.bidders);
          if (snap.progress) setProgress(snap.progress);
        } else if (eventType === "bidder_status_changed") {
          const { bidder_id, new_status } = data as {
            bidder_id: number;
            new_status: string;
          };
          setBidders((prev) =>
            prev.map((b) =>
              b.id === bidder_id ? { ...b, parse_status: new_status } : b,
            ),
          );
        } else if (
          eventType === "bidder_price_filled" ||
          eventType === "project_price_rule_ready" ||
          eventType === "document_role_classified"
        ) {
          // 这些事件需要重新拉数据(files/roles/items)
          void refetch();
        }
      };

    const events: ParseProgressEvent["event_type"][] = [
      "snapshot",
      "bidder_status_changed",
      "document_role_classified",
      "project_price_rule_ready",
      "bidder_price_filled",
      "error",
      "heartbeat",
    ];
    for (const name of events) {
      es.addEventListener(name, handler(name));
    }

    return () => {
      es.close();
      stopPolling();
      setConnected(false);
    };
  }, [projectId]);

  return { bidders, progress, connected, lastEvent };
}
