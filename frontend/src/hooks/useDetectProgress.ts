/**
 * C6 检测进度 hook
 *
 * - 主路径:EventSource 订阅 `/api/projects/{pid}/analysis/events`
 * - 断线兜底:onerror 后每 3s 轮询 `getAnalysisStatus(pid)`,重连成功后清 interval
 * - 根据 agent_status / report_ready 事件更新 agent_tasks 本地状态
 * - 暴露 `refetch()` 让启动检测后能立即拉一次状态(不等 SSE)
 * - 暴露 `lastEventAt` 给 UI 判断是否"静默"(超 10s 无事件 → 显示离线提示)
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "../services/api";
import { authStorage } from "../contexts/AuthContext";
import type {
  AgentTask,
  AnalysisStatusResponse,
  DetectEvent,
  ProjectAnalysisReport,
} from "../types";

export interface DetectProgressState {
  version: number | null;
  projectStatus: string;
  agentTasks: AgentTask[];
  /** SSE 已建立长连接,false = 走轮询兜底 */
  connected: boolean;
  /** 最近一次 report_ready 数据 */
  latestReport: ProjectAnalysisReport | null;
  /** 最近一个事件(调试/测试用) */
  lastEvent: DetectEvent | null;
  /** 最近一次事件/状态更新的时间戳(ms);用于 UI 判静默离线 */
  lastEventAt: number;
  /** 外部触发立即拉一次 status(启动检测后立即调,不等 SSE) */
  refetch: () => Promise<void>;
}

const POLL_INTERVAL_MS = 3000;

export function useDetectProgress(
  projectId: number | string | null,
): DetectProgressState {
  const [version, setVersion] = useState<number | null>(null);
  const [projectStatus, setProjectStatus] = useState<string>("draft");
  const [agentTasks, setAgentTasks] = useState<AgentTask[]>([]);
  const [connected, setConnected] = useState(false);
  const [latestReport, setLatestReport] =
    useState<ProjectAnalysisReport | null>(null);
  const [lastEvent, setLastEvent] = useState<DetectEvent | null>(null);
  const [lastEventAt, setLastEventAt] = useState<number>(Date.now());
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const projectIdRef = useRef(projectId);
  projectIdRef.current = projectId;

  const applyStatusRef = useRef<(s: AnalysisStatusResponse) => void>(() => {
    // placeholder;setup effect 会 assign 真实函数
  });

  const refetch = useCallback(async () => {
    const pid = projectIdRef.current;
    if (pid == null) return;
    try {
      const s = await api.getAnalysisStatus(pid);
      applyStatusRef.current(s);
    } catch {
      // ignore;轮询还会兜底
    }
  }, []);

  useEffect(() => {
    if (projectId == null) return;

    const applyStatus = (status: AnalysisStatusResponse) => {
      setVersion(status.version);
      setProjectStatus(status.project_status);
      setAgentTasks(status.agent_tasks);
      setLastEventAt(Date.now());
      // 已生成的报告摘要跟着 status 一起来,刷新页面后不必等 SSE report_ready 重放
      if (status.latest_report) {
        setLatestReport(status.latest_report);
      }
    };
    applyStatusRef.current = applyStatus;

    const startPolling = () => {
      if (pollRef.current) return;
      pollRef.current = setInterval(async () => {
        try {
          const s = await api.getAnalysisStatus(projectId);
          applyStatus(s);
        } catch {
          // 忽略轮询异常
        }
      }, POLL_INTERVAL_MS);
    };

    const stopPolling = () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };

    // 初始化:直接拉一次状态
    api.getAnalysisStatus(projectId).then(applyStatus).catch(() => {
      /* ignore */
    });

    // EventSource 不支持自定义 header → token 通过 query 附加
    const sseUrlBase = api.analysisEventsUrl(projectId);
    const sseToken = authStorage.getToken();
    const sseUrl = sseToken
      ? `${sseUrlBase}?access_token=${encodeURIComponent(sseToken)}`
      : sseUrlBase;
    const es = new EventSource(sseUrl, {
      withCredentials: false,
    });

    const handleEvent = (evt: MessageEvent, eventType: DetectEvent["event_type"]) => {
      setConnected(true);
      setLastEventAt(Date.now());
      stopPolling();
      try {
        const data = JSON.parse(evt.data);
        setLastEvent({ event_type: eventType, data });
        if (eventType === "snapshot") {
          applyStatus(data as AnalysisStatusResponse);
        } else if (eventType === "agent_status") {
          // 更新单个 AgentTask 状态
          setAgentTasks((prev) =>
            prev.map((t) =>
              t.id === (data as { agent_task_id: number }).agent_task_id
                ? {
                    ...t,
                    status: (data as { status: AgentTask["status"] }).status,
                    score: ((data as { score: number | null }).score?.toString() ??
                      null) as string | null,
                    summary: (data as { summary: string | null }).summary,
                    elapsed_ms: (data as { elapsed_ms: number | null })
                      .elapsed_ms,
                  }
                : t,
            ),
          );
        } else if (eventType === "report_ready") {
          const d = data as {
            version: number;
            total_score: number;
            risk_level: "high" | "medium" | "low";
          };
          setLatestReport({
            version: d.version,
            total_score: d.total_score,
            risk_level: d.risk_level,
            created_at: new Date().toISOString(),
          });
        }
      } catch {
        // 解析失败忽略
      }
    };

    es.addEventListener("snapshot", (e) =>
      handleEvent(e as MessageEvent, "snapshot"),
    );
    es.addEventListener("agent_status", (e) =>
      handleEvent(e as MessageEvent, "agent_status"),
    );
    es.addEventListener("report_ready", (e) =>
      handleEvent(e as MessageEvent, "report_ready"),
    );
    es.addEventListener("heartbeat", (e) =>
      handleEvent(e as MessageEvent, "heartbeat"),
    );

    es.onerror = () => {
      setConnected(false);
      startPolling();
    };

    es.onopen = () => {
      setConnected(true);
      stopPolling();
    };

    return () => {
      es.close();
      stopPolling();
    };
  }, [projectId]);

  return {
    version,
    projectStatus,
    agentTasks,
    connected,
    latestReport,
    lastEvent,
    lastEventAt,
    refetch,
  };
}
