/**
 * C6 检测进度 hook
 *
 * - 主路径:EventSource 订阅 `/api/projects/{pid}/analysis/events`
 * - 断线兜底:onerror 后每 3s 轮询 `getAnalysisStatus(pid)`,重连成功后清 interval
 * - 漏推兜底(fix-bug-triple-and-direction-high P10):active analysis 时,业务事件
 *   (snapshot/agent_status/report_ready/project_status_changed/error)35s 内未到 →
 *   启动 polling;heartbeat 不计入 lastBizEventAt(避免 SSE 假活症状漏掉)
 * - 根据 agent_status / report_ready / project_status_changed 事件更新本地状态
 * - 暴露 `refetch()` 让启动检测后能立即拉一次状态(不等 SSE)
 * - 暴露 `lastEventAt` 给 UI 判断是否"静默"(超 10s 无事件 → 显示离线提示)
 * - 暴露 `lastError` 供 UI 渲染 detect engine 异常错误状态
 *
 * fix-bug-triple-and-direction-high:
 * - hook projectStatus 初值从 "draft" 改 null,Tag 渲染处用 `??` 区分(避 `||` 反向)
 * - report_ready handler 兜底 setProjectStatus("completed"),双保险:任一事件先到都打 Tag
 * - 加 project_status_changed / error listener
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "../services/api";
import { authStorage } from "../contexts/AuthContext";
import type {
  AgentTask,
  AnalysisStatusResponse,
  DetectEvent,
  ProjectAnalysisReport,
  RiskLevel,
} from "../types";

export interface DetectErrorInfo {
  stage: string;
  message: string;
  receivedAt: number;
}

export interface DetectProgressState {
  version: number | null;
  /** 项目状态;null 表示尚未拿到 SSE/initial fetch 的权威值 */
  projectStatus: string | null;
  agentTasks: AgentTask[];
  /** SSE 已建立长连接,false = 走轮询兜底 */
  connected: boolean;
  /** 最近一次 report_ready 数据 */
  latestReport: ProjectAnalysisReport | null;
  /** 最近一个事件(调试/测试用) */
  lastEvent: DetectEvent | null;
  /** 最近一次事件/状态更新的时间戳(ms);用于 UI 判静默离线 */
  lastEventAt: number;
  /** detect engine 异常 error event payload(P3 双保险用 SSE 协议消费) */
  lastError: DetectErrorInfo | null;
  /** 外部触发立即拉一次 status(启动检测后立即调,不等 SSE) */
  refetch: () => Promise<void>;
}

const POLL_INTERVAL_MS = 3000;
/** watchdog 阈值:≥ 2 × HEARTBEAT_INTERVAL_S(15s) + 5s tolerance,避免 heartbeat 间隙误触 */
const WATCHDOG_BIZ_EVENT_TIMEOUT_MS = 35_000;
const WATCHDOG_CHECK_INTERVAL_MS = 5_000;

export function useDetectProgress(
  projectId: number | string | null,
): DetectProgressState {
  const [version, setVersion] = useState<number | null>(null);
  const [projectStatus, setProjectStatus] = useState<string | null>(null);
  const [agentTasks, setAgentTasks] = useState<AgentTask[]>([]);
  const [connected, setConnected] = useState(false);
  const [latestReport, setLatestReport] =
    useState<ProjectAnalysisReport | null>(null);
  const [lastEvent, setLastEvent] = useState<DetectEvent | null>(null);
  const [lastEventAt, setLastEventAt] = useState<number>(Date.now());
  const [lastError, setLastError] = useState<DetectErrorInfo | null>(null);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const watchdogRef = useRef<ReturnType<typeof setInterval> | null>(null);
  /**
   * 业务事件最近时间(不含 heartbeat)。watchdog 据此判断 "SSE connected
   * 但业务事件漏推" 的假活症状。
   */
  const lastBizEventAtRef = useRef<number>(Date.now());
  const projectIdRef = useRef(projectId);
  projectIdRef.current = projectId;
  /** projectStatus 当前值的 ref,watchdog 使用避免闭包过期 */
  const projectStatusRef = useRef<string | null>(projectStatus);
  projectStatusRef.current = projectStatus;

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
      const now = Date.now();
      setLastEventAt(now);
      lastBizEventAtRef.current = now;
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

    /**
     * watchdog:active analysis 期间,若业务事件(非 heartbeat)在
     * WATCHDOG_BIZ_EVENT_TIMEOUT_MS 内未到 → 启动 polling。
     * 关键:SSE connected=true 但 backend 漏 publish / broker 丢消息时,
     * onerror 不会触发,只能靠这条兜底。
     */
    watchdogRef.current = setInterval(() => {
      if (projectStatusRef.current !== "analyzing") return;
      const elapsed = Date.now() - lastBizEventAtRef.current;
      if (elapsed >= WATCHDOG_BIZ_EVENT_TIMEOUT_MS) {
        startPolling();
      }
    }, WATCHDOG_CHECK_INTERVAL_MS);

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

    const handleEvent = (
      evt: MessageEvent,
      eventType: DetectEvent["event_type"],
    ) => {
      setConnected(true);
      const now = Date.now();
      setLastEventAt(now);
      // heartbeat 不算业务事件,避免 watchdog 反向 bug(SSE 假活时永不触发)
      if (eventType !== "heartbeat") {
        lastBizEventAtRef.current = now;
        stopPolling();
      }
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
          // honest-detection-results: risk_level 收紧为 RiskLevel union(含 indeterminate)
          const d = data as {
            version: number;
            total_score: number;
            risk_level: RiskLevel;
          };
          setLatestReport({
            version: d.version,
            total_score: d.total_score,
            risk_level: d.risk_level,
            created_at: new Date().toISOString(),
          });
          // P3 双保险:report_ready handler 同步把状态刷成 completed,
          // 任一事件先到都能打 Tag(避 status_changed/report_ready 顺序 race)
          setProjectStatus("completed");
        } else if (eventType === "project_status_changed") {
          const d = data as { new_status: string };
          setProjectStatus(d.new_status);
        } else if (eventType === "error") {
          const d = data as { stage?: string; message?: string };
          setLastError({
            stage: d.stage ?? "unknown",
            message: d.message ?? "",
            receivedAt: now,
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
    es.addEventListener("project_status_changed", (e) =>
      handleEvent(e as MessageEvent, "project_status_changed"),
    );
    es.addEventListener("error", (e) =>
      handleEvent(e as MessageEvent, "error"),
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
      if (watchdogRef.current) {
        clearInterval(watchdogRef.current);
        watchdogRef.current = null;
      }
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
    lastError,
    refetch,
  };
}
